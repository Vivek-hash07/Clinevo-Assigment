from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_RETRYABLE = frozenset({408, 409, 429, 500, 502, 503, 504})


class LlmError(Exception):
    def __init__(self, message: str, status_code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True)
class LlmCompletion:
    data: dict[str, Any]
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0
    raw_text: str = ""


def parse_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("LLM returned empty content")
    raw = _FENCE.sub("", raw).strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("LLM JSON was not an object")
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("LLM did not return JSON") from None
        parsed = json.loads(raw[start : end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("LLM JSON was not an object")
        return parsed


class OpenRouterClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def available(self) -> bool:
        return bool(self.settings.openrouter_api_key)

    def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4000,
        timeout: float | None = None,
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "result",
    ) -> LlmCompletion:
        if not self.available:
            raise LlmError("OPENROUTER_API_KEY is not set", retryable=False)
        chosen = model or self.settings.openrouter_model
        payload: dict[str, Any] = {
            "model": chosen,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": self._response_format(json_schema, schema_name),
        }
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "X-Title": self.settings.openrouter_app_title,
        }
        referer = self.settings.openrouter_http_referer or self.settings.backend_url
        if referer:
            headers["HTTP-Referer"] = referer
        url = self.settings.openrouter_base_url.rstrip("/") + "/chat/completions"
        timeout_s = timeout if timeout is not None else float(self.settings.openrouter_timeout_seconds)
        started = time.monotonic()
        try:
            body = self._post(url, headers, payload, timeout_s)
        except LlmError as exc:
            if json_schema and self._should_fallback_json_object(exc):
                logger.warning("Structured json_schema unsupported; falling back to json_object")
                payload = dict(payload)
                payload["response_format"] = {"type": "json_object"}
                payload["messages"] = self._with_schema_hint(messages, json_schema, schema_name)
                body = self._post(url, headers, payload, timeout_s)
            else:
                raise
        latency_ms = int((time.monotonic() - started) * 1000)
        content = (((body.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
        usage_raw = body.get("usage") or {}
        usage = {
            "prompt_tokens": int(usage_raw.get("prompt_tokens") or 0),
            "completion_tokens": int(usage_raw.get("completion_tokens") or 0),
            "total_tokens": int(usage_raw.get("total_tokens") or 0),
        }
        try:
            data = parse_json_object(content if isinstance(content, str) else json.dumps(content))
        except (ValueError, json.JSONDecodeError) as exc:
            raise LlmError(f"OpenRouter returned non-JSON content: {exc}", retryable=True) from exc
        return LlmCompletion(
            data=data,
            model=str(body.get("model") or chosen),
            usage=usage,
            latency_ms=latency_ms,
            raw_text=content if isinstance(content, str) else json.dumps(content),
        )

    @staticmethod
    def _response_format(json_schema: dict[str, Any] | None, schema_name: str) -> dict[str, Any]:
        if not json_schema:
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name[:64],
                "strict": True,
                "schema": json_schema,
            },
        }

    @staticmethod
    def _should_fallback_json_object(exc: LlmError) -> bool:
        if exc.status_code not in {400, 404, 422}:
            return False
        text = str(exc).lower()
        needles = ("json_schema", "response_format", "structured", "strict")
        return any(part in text for part in needles)

    @staticmethod
    def _with_schema_hint(
        messages: list[dict[str, Any]],
        json_schema: dict[str, Any],
        schema_name: str,
    ) -> list[dict[str, Any]]:
        hint = (
            f"Your JSON must match schema '{schema_name}' exactly. "
            f"Schema: {json.dumps(json_schema, ensure_ascii=False)}"
        )
        cloned = [dict(item) for item in messages]
        cloned.append({"role": "user", "content": hint})
        return cloned

    def _post(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_s: float,
    ) -> dict[str, Any]:
        delay = 0.8
        last_error: Exception | None = None
        attempts = max(1, int(self.settings.openrouter_max_retries) + 1)
        for attempt in range(attempts):
            try:
                with httpx.Client(timeout=httpx.Timeout(timeout_s, connect=15.0)) as client:
                    response = client.post(url, headers=headers, json=payload)
                if response.status_code in _RETRYABLE:
                    last_error = LlmError(
                        f"OpenRouter HTTP {response.status_code}: {response.text[:300]}",
                        status_code=response.status_code,
                        retryable=True,
                    )
                    if attempt + 1 >= attempts:
                        raise last_error
                    time.sleep(delay)
                    delay = min(delay * 2, 8.0)
                    continue
                if response.status_code >= 400:
                    retryable = response.status_code >= 500
                    raise LlmError(
                        f"OpenRouter HTTP {response.status_code}: {response.text[:300]}",
                        status_code=response.status_code,
                        retryable=retryable,
                    )
                data = response.json()
                if not isinstance(data, dict):
                    raise LlmError("OpenRouter response was not a JSON object", retryable=True)
                return data
            except httpx.TimeoutException as exc:
                last_error = LlmError("OpenRouter request timed out", retryable=True)
                logger.warning("OpenRouter timeout (attempt %s/%s)", attempt + 1, attempts)
                if attempt + 1 >= attempts:
                    raise last_error from exc
                time.sleep(delay)
                delay = min(delay * 2, 8.0)
            except httpx.HTTPError as exc:
                last_error = LlmError(f"OpenRouter transport error: {exc}", retryable=True)
                if attempt + 1 >= attempts:
                    raise last_error from exc
                time.sleep(delay)
                delay = min(delay * 2, 8.0)
        raise last_error or LlmError("OpenRouter request failed", retryable=True)


def get_llm_client() -> OpenRouterClient:
    return OpenRouterClient()
