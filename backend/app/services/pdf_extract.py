from __future__ import annotations

import re
from typing import Any

import pdfplumber
from pdfplumber.page import Page

from app.services.pdf_flavor import PageSignals, alphanumeric_ratio, estimate_column_count

_WS = re.compile(r"[ \t]+\n")
_MULTI = re.compile(r"\n{3,}")


def _clean_text(text: str) -> str:
    cleaned = _WS.sub("\n", (text or "").replace("\x00", " "))
    cleaned = _MULTI.sub("\n\n", cleaned)
    return cleaned.strip()


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return _clean_text(str(value))


def collect_signals(page: Page, page_number: int) -> PageSignals:
    width = float(page.width or 0)
    height = float(page.height or 0)
    area = max(width * height, 1.0)
    words = page.extract_words() or []
    raw = page.extract_text() or ""
    chars = page.chars or []
    images = page.images or []
    image_area = 0.0
    for image in images:
        try:
            img_w = abs(float(image.get("x1", 0) - image.get("x0", 0)))
            img_h = abs(float(image.get("y1", 0) - image.get("y0", 0)))
            image_area += img_w * img_h
        except (TypeError, ValueError):
            continue
    lines = [line for line in raw.splitlines() if line.strip()]
    short_lines = sum(1 for line in lines if len(line.strip()) <= 28)
    mids = []
    for word in words:
        try:
            mids.append((float(word["x0"]) + float(word["x1"])) / 2.0)
        except (KeyError, TypeError, ValueError):
            continue
    sample = _clean_text(raw)[:800]
    char_count = len(raw.strip())
    return PageSignals(
        page_number=page_number,
        width=width,
        height=height,
        char_count=char_count,
        word_count=len(words),
        line_count=len(lines),
        image_count=len(images),
        image_area_ratio=min(1.0, image_area / area),
        column_count=estimate_column_count(mids, width),
        text_density=char_count / area,
        alphanumeric_ratio=alphanumeric_ratio(raw),
        sample_text=sample,
        has_text_layer=char_count >= 8 or len(chars) >= 8,
        short_line_ratio=(short_lines / len(lines)) if lines else 0.0,
    )


def _join_words(words: list[dict], y_bucket: float = 3.0) -> str:
    ordered = sorted(
        words,
        key=lambda word: (round(float(word.get("top", 0)) / y_bucket), float(word.get("x0", 0))),
    )
    if not ordered:
        return ""
    lines: list[str] = []
    current_key = None
    current: list[str] = []
    for word in ordered:
        key = round(float(word.get("top", 0)) / y_bucket)
        token = str(word.get("text") or "").strip()
        if not token:
            continue
        if current_key is None:
            current_key = key
        if key != current_key:
            lines.append(" ".join(current))
            current = [token]
            current_key = key
        else:
            current.append(token)
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def extract_column_text(page: Page) -> str:
    words = page.extract_words() or []
    width = float(page.width or 0)
    if width <= 0 or len(words) < 30:
        return _clean_text(page.extract_text(layout=True) or page.extract_text() or "")
    mid = width / 2.0
    left: list[dict] = []
    right: list[dict] = []
    for word in words:
        try:
            center = (float(word["x0"]) + float(word["x1"])) / 2.0
        except (KeyError, TypeError, ValueError):
            continue
        (left if center < mid - 8 else right).append(word)
    if len(left) < 10 or len(right) < 10:
        return _clean_text(page.extract_text(layout=True) or page.extract_text() or "")
    return _clean_text(_join_words(left) + "\n\n" + _join_words(right))


def extract_digital_text(page: Page, signals: PageSignals) -> tuple[str, str]:
    if signals.column_count >= 2:
        text = extract_column_text(page)
        if len(text) >= 40:
            return text, "pdfplumber_columns"
    layout = _clean_text(page.extract_text(layout=True) or "")
    raw = _clean_text(page.extract_text() or "")
    if layout and raw:
        layout_alpha = alphanumeric_ratio(layout)
        raw_alpha = alphanumeric_ratio(raw)
        if layout_alpha + 0.08 < raw_alpha and len(raw) >= 20:
            return raw, "pdfplumber"
        if signals.short_line_ratio >= 0.45:
            return layout or raw, "pdfplumber_layout"
        if signals.column_count == 1:
            return raw or layout, "pdfplumber"
        return (layout if len(layout) >= len(raw) * 0.6 else raw), "pdfplumber"
    return (layout or raw), "pdfplumber"


def extract_tables(page: Page) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        tables = page.extract_tables() or []
    except Exception:
        return items
    for table in tables:
        if not table:
            continue
        rows = [[_cell(cell) for cell in row] for row in table if row]
        if not rows:
            continue
        headers = rows[0]
        body = rows[1:]
        if not any(headers) and not any(any(row) for row in body):
            continue
        items.append({"caption": "", "headers": headers, "rows": body, "source": "pdfplumber"})
    return items


def tables_look_broken(tables: list[dict[str, Any]]) -> bool:
    if not tables:
        return False
    for table in tables:
        headers = table.get("headers") or []
        rows = table.get("rows") or []
        width = len(headers)
        if width <= 1 and not rows:
            return True
        ragged = sum(1 for row in rows if len(row) != width)
        if rows and ragged / len(rows) > 0.5:
            return True
        empty_rows = sum(1 for row in rows if not any(str(cell).strip() for cell in row))
        if rows and empty_rows / len(rows) > 0.6:
            return True
    return False
