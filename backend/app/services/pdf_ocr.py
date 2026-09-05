from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from PIL import Image

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OcrResult:
    text: str
    confidence: float | None
    available: bool
    engine: str = "tesseract"


def tesseract_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def render_page(pdf_bytes: bytes, page_number: int, scale: float | None = None) -> Image.Image:
    import pypdfium2 as pdfium

    settings = get_settings()
    render_scale = float(scale if scale is not None else settings.pdf_render_scale)
    render_scale = min(max(render_scale, 1.0), 4.0)
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        index = page_number - 1
        if index < 0 or index >= len(document):
            raise ValueError(f"page {page_number} is out of range")
        page = document[index]
        bitmap = page.render(scale=render_scale)
        return bitmap.to_pil().convert("RGB")
    finally:
        document.close()


def encode_page_image(image: Image.Image, max_side: int = 1600, quality: int = 75) -> tuple[bytes, str]:
    frame = image.convert("RGB")
    frame.thumbnail((max_side, int(max_side * 1.4)))
    buffer = io.BytesIO()
    frame.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue(), "image/jpeg"


def image_data_url(image: Image.Image) -> str:
    import base64

    blob, mime = encode_page_image(image)
    encoded = base64.b64encode(blob).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def ocr_page(image: Image.Image, lang: str = "eng") -> OcrResult:
    if not tesseract_available():
        return OcrResult(text="", confidence=None, available=False, engine="none")
    try:
        import pytesseract
        from pytesseract import Output
    except Exception as exc:
        logger.warning("pytesseract import failed: %s", exc)
        return OcrResult(text="", confidence=None, available=False, engine="none")

    try:
        text = (pytesseract.image_to_string(image, lang=lang) or "").strip()
        data = pytesseract.image_to_data(image, lang=lang, output_type=Output.DICT)
        confs: list[float] = []
        for raw in data.get("conf") or []:
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value >= 0:
                confs.append(value)
        confidence = round(sum(confs) / len(confs) / 100.0, 4) if confs else None
        return OcrResult(text=text, confidence=confidence, available=True, engine="tesseract")
    except Exception as exc:
        logger.warning("Tesseract OCR failed: %s", exc)
        return OcrResult(text="", confidence=None, available=True, engine="tesseract")
