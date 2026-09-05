from __future__ import annotations

import threading

from app.services.pdf_flavor import clamp01

_LOCK = threading.Lock()
_ENGLISH = frozenset({"en", "eng", "english"})


def normalize_lang(code: str | None) -> str:
    raw = (code or "").strip().lower().replace("_", "-")
    if not raw:
        return "und"
    primary = raw.split("-", 1)[0]
    aliases = {"eng": "en", "fre": "fr", "fra": "fr", "deu": "de", "ger": "de", "spa": "es", "chi": "zh"}
    if raw in _ENGLISH or primary in _ENGLISH:
        return "en"
    return aliases.get(primary, primary)[:8]


def is_english(code: str | None) -> bool:
    return normalize_lang(code) == "en"


def detect_language_local(text: str) -> tuple[str | None, float]:
    sample = (text or "").strip()
    if len(sample) < 24:
        return None, 0.0
    try:
        from langdetect import LangDetectException, detect_langs
    except Exception:
        return None, 0.0
    try:
        with _LOCK:
            guesses = detect_langs(sample[:4000])
    except LangDetectException:
        return None, 0.0
    except Exception:
        return None, 0.0
    if not guesses:
        return None, 0.0
    best = guesses[0]
    return normalize_lang(getattr(best, "lang", None)), clamp01(float(getattr(best, "prob", 0.0)))


def choose_language(
    local_code: str | None,
    local_confidence: float,
    llm_code: str | None,
    llm_confidence: float,
    text: str,
) -> tuple[str, float]:
    llm_lang = normalize_lang(llm_code) if llm_code else "und"
    local_lang = normalize_lang(local_code) if local_code else "und"
    llm_conf = clamp01(llm_confidence)
    local_conf = clamp01(local_confidence)

    if llm_lang != "und" and llm_conf >= 0.5:
        # Short medical English is often mislabeled by langdetect; trust the LLM there.
        if local_lang != "und" and local_lang != llm_lang and local_conf >= 0.97 and len(text) > 400:
            return local_lang, local_conf
        return llm_lang, max(llm_conf, local_conf if local_lang == llm_lang else llm_conf)
    if local_lang != "und":
        return local_lang, local_conf
    return "und", 0.0


def working_texts(original: str, translated: str | None, language: str) -> tuple[str, str | None]:
    original_text = (original or "").strip()
    english = (translated or "").strip() or None
    if is_english(language):
        return original_text, None
    if english and english != original_text:
        return original_text, english
    return original_text, english
