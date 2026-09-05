from __future__ import annotations

from dataclasses import dataclass

from app.services.mail import send_mail


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_simple_pdf(title: str, paragraphs: list[str]) -> bytes:
    lines = [title[:80], "", *[paragraph[:110] for paragraph in paragraphs]]
    y_commands = ["BT", "/F1 12 Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        escaped = _pdf_escape(line or " ")
        if index == 0:
            y_commands.append(f"({escaped}) Tj")
        else:
            y_commands.append(f"0 -16 Td ({escaped}) Tj")
    y_commands.append("ET")
    stream = "\n".join(y_commands).encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
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


@dataclass(frozen=True)
class SyntheticEmail:
    key: str
    subject: str
    text_body: str
    attachments: list[tuple[str, str, bytes]]


def synthetic_catalog() -> list[SyntheticEmail]:
    icsr_pdf = build_simple_pdf(
        "Fictional safety note — not a real patient",
        [
            "Patient: Alex Rivera (made-up)",
            "Age: 54 years. Sex: female.",
            "Product: Clinevo Examplemab 40 mg, subcutaneous.",
            "Event: widespread rash two days after the third dose.",
            "Outcome: recovering. This document is synthetic sample data.",
        ],
    )
    return [
        SyntheticEmail(
            key="icsr-body",
            subject="[SYNTHETIC] Possible reaction after Examplemab — fictional case",
            text_body=(
                "This is synthetic mailbox data for the Clinevo reviewer prototype. "
                "No real patient is described.\n\n"
                "Reporter (fictional nurse) says a 54-year-old woman developed a rash "
                "and fever after Examplemab 40 mg. She was seen in clinic and is recovering.\n"
            ),
            attachments=[],
        ),
        SyntheticEmail(
            key="icsr-pdf",
            subject="[SYNTHETIC] Safety report with PDF case note — fictional",
            text_body=(
                "Please find a made-up clinic note attached. This email is only for pipeline testing.\n"
                "The attached PDF describes a fictional rash after Examplemab.\n"
            ),
            attachments=[("fictional-safety-note.pdf", "application/pdf", icsr_pdf)],
        ),
        SyntheticEmail(
            key="pqc-csv",
            subject="[SYNTHETIC] Bottle arrived with a broken seal — fictional product complaint",
            text_body=(
                "Warehouse note (synthetic): a bottle of Exampletab 10 mg arrived with a torn seal "
                "and cracked cap. Lot EX-4401. No patient was involved.\n"
                "A CSV packing list is attached on purpose so the intake job can log a non-PDF file.\n"
            ),
            attachments=[
                (
                    "packing-list.csv",
                    "text/csv",
                    b"lot,issue,fictional\nEX-4401,broken seal,yes\n",
                )
            ],
        ),
        SyntheticEmail(
            key="mi",
            subject="[SYNTHETIC] Question about Exampletab dosing with food — fictional MI",
            text_body=(
                "Hello medical information (synthetic request),\n\n"
                "Can Exampletab 10 mg be taken with breakfast, and is there an interaction with omeprazole?\n"
                "No adverse event and no product defect is being reported.\n"
            ),
            attachments=[],
        ),
        SyntheticEmail(
            key="not-relevant",
            subject="[SYNTHETIC] Industry conference invitation — not a case",
            text_body=(
                "Join the fictional Clinevo summer science mixer. This is marketing mail and should "
                "classify as not relevant. No patient, product quality, or medical question is included.\n"
            ),
            attachments=[],
        ),
    ]


def send_synthetic_mailbox(to_email: str, keys: list[str] | None = None) -> dict:
    catalog = {item.key: item for item in synthetic_catalog()}
    selected = [catalog[key] for key in keys] if keys else list(catalog.values())
    sent: list[str] = []
    for item in selected:
        send_mail(
            to_email,
            item.subject,
            item.text_body,
            attachments=item.attachments,
        )
        sent.append(item.key)
    return {"to": to_email, "sent": sent, "count": len(sent)}
