"""Build tiny synthetic PDFs: digital text, two-column articles, and image-only scans."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SYNTHETIC_BANNER = "SYNTHETIC / FICTIONAL — not a real patient, product complaint, or publication."

_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
_HAND_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Brush Script.ttf",
    "/System/Library/Fonts/MarkerFelt.ttc",
    "/System/Library/Fonts/Supplemental/Chalkboard.ttc",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
)


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _winansi(text: str) -> str:
    return text.encode("cp1252", errors="replace").decode("cp1252")


def _wrap(text: str, width: int) -> list[str]:
    words = text.replace("\n", " \n ").split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        if word == "\n":
            lines.append(" ".join(current) if current else "")
            current = []
            continue
        trial = " ".join(current + [word])
        if len(trial) > width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines or [""]


def _pdf_from_commands(commands: list[str], page_count: int = 1) -> bytes:
    content = "\n".join(commands).encode("latin-1", errors="replace")
    kids = " ".join(f"{3 + i} 0 R" for i in range(page_count))
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode("ascii"),
    ]
    # Page objects then one shared content + font. Single-page builder uses objects 3,4,5.
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>"
    )
    objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    return _assemble(objects)


def _assemble(objects: list[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{index} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref_at = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.extend(
        (
            f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(out)


def build_simple_pdf(title: str, paragraphs: list[str]) -> bytes:
    lines = [SYNTHETIC_BANNER, "", title[:90], "", *[paragraph[:110] for paragraph in paragraphs]]
    commands = ["BT", "/F1 11 Tf", "54 740 Td"]
    for index, line in enumerate(lines):
        escaped = _pdf_escape(_winansi(line or " "))
        if index == 0:
            commands.append(f"({escaped}) Tj")
        else:
            commands.append(f"0 -14 Td ({escaped}) Tj")
    commands.append("ET")
    return _pdf_from_commands(commands)


def build_article_pdf(
    title: str,
    authors: str,
    abstract: str,
    left_paragraphs: list[str],
    right_paragraphs: list[str],
    references: list[str] | None = None,
) -> bytes:
    """Two-column fictional article so the flavor detector sees an article layout."""
    commands = [
        "BT",
        "/F1 9 Tf",
        f"54 760 Td ({_pdf_escape(_winansi(SYNTHETIC_BANNER))}) Tj",
        "0 -18 Td /F1 14 Tf",
        f"({_pdf_escape(_winansi(title[:88]))}) Tj",
        "0 -14 Td /F1 10 Tf",
        f"({_pdf_escape(_winansi(authors[:90]))}) Tj",
        "0 -12 Td /F1 9 Tf",
        f"(Fictional Pharmacovigilance Letters 2024;12:1-2. Made-up sample.) Tj",
        "ET",
    ]
    abstract_lines = _wrap("Abstract. " + abstract, 32)
    y = 690
    commands.append("BT /F1 9 Tf")
    for i, line in enumerate(abstract_lines[:6]):
        if i == 0:
            commands.append(f"54 {y} Td ({_pdf_escape(_winansi(line))}) Tj")
        else:
            commands.append(f"0 -11 Td ({_pdf_escape(_winansi(line))}) Tj")
    commands.append("ET")

    def column_commands(paragraphs: list[str], x: int, start_y: int, width: int) -> list[str]:
        lines: list[str] = []
        for para in paragraphs:
            lines.extend(_wrap(para, width))
            lines.append("")
        out = ["BT /F1 9 Tf"]
        for i, line in enumerate(lines[:42]):
            text = _pdf_escape(_winansi((line or " ")[:width]))
            if i == 0:
                out.append(f"{x} {start_y} Td ({text}) Tj")
            else:
                out.append(f"0 -12 Td ({text}) Tj")
        out.append("ET")
        return out

    commands.extend(column_commands(left_paragraphs, 54, 610, 32))
    commands.extend(column_commands(right_paragraphs, 410, 610, 32))
    if references:
        ref_y = 70
        commands.append("BT /F1 8 Tf")
        commands.append(f"54 {ref_y} Td ({_pdf_escape('References (fictional)')}) Tj")
        for ref in references[:3]:
            commands.append(f"0 -10 Td ({_pdf_escape(_winansi(ref[:100]))}) Tj")
        commands.append("ET")
    return _pdf_from_commands(commands)


def _load_font(candidates: tuple[str, ...], size: int) -> ImageFont.ImageFont:
    for path in candidates:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def build_image_pdf(
    title: str,
    lines: list[str],
    *,
    handwritten: bool = False,
    size: tuple[int, int] = (1275, 1650),
) -> bytes:
    """Image-only PDF (no text layer) so the scan/OCR branch runs."""
    image = Image.new("RGB", size, (248, 246, 239) if handwritten else (255, 255, 255))
    draw = ImageDraw.Draw(image)
    title_font = _load_font(_HAND_CANDIDATES if handwritten else _FONT_CANDIDATES, 36 if handwritten else 28)
    body_font = _load_font(_HAND_CANDIDATES if handwritten else _FONT_CANDIDATES, 28 if handwritten else 22)
    banner_font = _load_font(_FONT_CANDIDATES, 16)
    y = 48
    draw.text((48, y), SYNTHETIC_BANNER, fill=(80, 90, 80), font=banner_font)
    y += 42
    draw.text((48, y), title[:80], fill=(20, 36, 31), font=title_font)
    y += 56
    ink = (36, 28, 64) if handwritten else (20, 20, 20)
    for raw in lines:
        text = raw[:110]
        if handwritten:
            x = 56
            for index, char in enumerate(text):
                jitter_y = ((index * 7) % 5) - 2
                jitter_x = ((index * 3) % 3)
                draw.text((x + jitter_x, y + jitter_y), char, fill=ink, font=body_font)
                x += 15
        else:
            draw.text((56, y), text, fill=ink, font=body_font)
        y += 40 if handwritten else 34
        if y > size[1] - 80:
            break
    buffer = io.BytesIO()
    image.save(buffer, format="PDF", resolution=150.0)
    return buffer.getvalue()


def build_scanned_pdf(title: str, lines: list[str]) -> bytes:
    return build_image_pdf(title, lines, handwritten=False)


def build_handwritten_pdf(title: str, lines: list[str]) -> bytes:
    return build_image_pdf(title, lines, handwritten=True)


def write_pdf(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
