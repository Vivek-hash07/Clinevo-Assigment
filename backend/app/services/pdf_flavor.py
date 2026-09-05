from __future__ import annotations

from dataclasses import dataclass, field

from app.constants import (
    FLAVOR_ARTICLE,
    FLAVOR_DIGITAL,
    FLAVOR_FORM,
    FLAVOR_HANDWRITTEN,
    FLAVOR_MIXED,
    FLAVOR_SCANNED,
    FLAVOR_UNKNOWN,
    PDF_FLAVORS,
)


@dataclass(frozen=True)
class PageSignals:
    page_number: int
    width: float
    height: float
    char_count: int
    word_count: int
    line_count: int
    image_count: int
    image_area_ratio: float
    column_count: int
    text_density: float
    alphanumeric_ratio: float
    sample_text: str
    has_text_layer: bool
    short_line_ratio: float = 0.0


@dataclass
class FlavorDecision:
    flavor: str
    confidence: float
    reasons: list[str] = field(default_factory=list)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def normalize_flavor(value: str | None, fallback: str = FLAVOR_UNKNOWN) -> str:
    raw = (value or "").strip().lower()
    if raw in PDF_FLAVORS:
        return raw
    aliases = {
        "text": FLAVOR_DIGITAL,
        "native": FLAVOR_DIGITAL,
        "born-digital": FLAVOR_DIGITAL,
        "scan": FLAVOR_SCANNED,
        "image": FLAVOR_SCANNED,
        "image-only": FLAVOR_SCANNED,
        "handwriting": FLAVOR_HANDWRITTEN,
        "script": FLAVOR_HANDWRITTEN,
        "literature": FLAVOR_ARTICLE,
        "multi-column": FLAVOR_ARTICLE,
        "questionnaire": FLAVOR_FORM,
    }
    return aliases.get(raw, fallback)


def estimate_column_count(word_mids: list[float], page_width: float) -> int:
    if len(word_mids) < 30 or page_width <= 0:
        return 1
    gutter_min = page_width * 0.35
    gutter_max = page_width * 0.65
    left = sum(1 for mid in word_mids if mid < gutter_min)
    right = sum(1 for mid in word_mids if mid > gutter_max)
    middle = sum(1 for mid in word_mids if gutter_min <= mid <= gutter_max)
    if left > 15 and right > 15 and middle < 0.25 * (left + right):
        return 2
    return 1


def alphanumeric_ratio(text: str) -> float:
    compact = [ch for ch in text if not ch.isspace()]
    if not compact:
        return 0.0
    good = sum(1 for ch in compact if ch.isalnum() or ch in ".,;:/%+-()[]'\"")
    return good / len(compact)


def detect_flavor(signals: PageSignals) -> FlavorDecision:
    reasons: list[str] = []
    scanned_like = signals.char_count < 40 and (signals.image_count >= 1 or signals.image_area_ratio >= 0.25)
    weak_layer = signals.has_text_layer and signals.alphanumeric_ratio < 0.45 and signals.char_count < 220
    dense_text = signals.char_count >= 80 and signals.alphanumeric_ratio >= 0.55
    lots_of_image = signals.image_area_ratio >= 0.45 or signals.image_count >= 3

    if scanned_like or (not signals.has_text_layer and signals.image_count >= 1):
        reasons.append("sparse-or-missing text layer with page image")
        return FlavorDecision(FLAVOR_SCANNED, 0.86 if signals.image_count else 0.7, reasons)

    if weak_layer:
        reasons.append("text layer looks like OCR garbage")
        return FlavorDecision(FLAVOR_SCANNED, 0.72, reasons)

    if signals.column_count >= 2 and signals.char_count >= 200:
        reasons.append("two-column layout")
        return FlavorDecision(FLAVOR_ARTICLE, 0.8, reasons)

    if signals.short_line_ratio >= 0.55 and signals.word_count >= 20 and signals.word_count <= 400:
        reasons.append("many short lines, likely a form")
        return FlavorDecision(FLAVOR_FORM, 0.62, reasons)

    if dense_text and lots_of_image:
        reasons.append("native text plus large images")
        return FlavorDecision(FLAVOR_MIXED, 0.68, reasons)

    if dense_text:
        reasons.append("dense native text layer")
        conf = 0.9 if signals.image_area_ratio < 0.2 else 0.78
        return FlavorDecision(FLAVOR_DIGITAL, conf, reasons)

    if signals.char_count >= 40:
        reasons.append("partial text layer")
        return FlavorDecision(FLAVOR_DIGITAL, 0.55, reasons)

    reasons.append("not enough signal")
    return FlavorDecision(FLAVOR_UNKNOWN, 0.35, reasons)


def should_rasterize(signals: PageSignals, flavor: str) -> bool:
    if flavor in {FLAVOR_SCANNED, FLAVOR_UNKNOWN}:
        return True
    if signals.char_count < 40:
        return True
    if signals.alphanumeric_ratio < 0.45 and signals.char_count < 200:
        return True
    return False


def page_source_ref(attachment_id: str, page_number: int) -> str:
    return f"pdf:{attachment_id}:page:{page_number}"
