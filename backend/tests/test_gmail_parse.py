from app.services.gmail_parse import html_to_text, is_pdf, parse_gmail_message
from app.services.synthetic import build_simple_pdf


def test_html_to_text_strips_markup():
    text = html_to_text("<p>Hello <b>world</b></p><style>bad{}</style><p>Next</p>")
    assert "Hello" in text
    assert "world" in text
    assert "bad" not in text


def test_is_pdf_by_mime_and_name():
    assert is_pdf("note.PDF", "application/octet-stream")
    assert is_pdf("note.bin", "application/pdf")
    assert not is_pdf("sheet.csv", "text/csv")


def test_parse_plain_gmail_payload():
    import base64

    body = base64.urlsafe_b64encode(b"Patient had a rash after Examplemab.").decode("ascii").rstrip("=")
    raw = {
        "id": "msg-1",
        "threadId": "thr-1",
        "internalDate": "1710000000000",
        "snippet": "Patient had a rash",
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "Nurse Example <nurse@example.com>"},
                {"name": "Subject", "value": "Fictional safety report"},
                {"name": "Date", "value": "Sun, 10 Mar 2024 12:00:00 +0000"},
            ],
            "body": {"data": body, "size": 20},
        },
    }
    parsed = parse_gmail_message(raw)
    assert parsed.is_inbox
    assert parsed.sender == "Nurse Example <nurse@example.com>"
    assert parsed.subject == "Fictional safety report"
    assert "rash" in parsed.body_text
    assert parsed.attachments == []


def test_parse_skips_non_pdf_and_keeps_pdf_part():
    raw = {
        "id": "msg-2",
        "threadId": "thr-2",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Subject", "value": "With files"}],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": "SGVsbG8=", "size": 5},
                },
                {
                    "filename": "case-note.pdf",
                    "mimeType": "application/pdf",
                    "body": {"attachmentId": "att-pdf", "size": 1200},
                },
                {
                    "filename": "packing-list.csv",
                    "mimeType": "text/csv",
                    "body": {"attachmentId": "att-csv", "size": 40},
                },
            ],
        },
    }
    parsed = parse_gmail_message(raw)
    names = {item.filename: item.is_pdf for item in parsed.attachments}
    assert names["case-note.pdf"] is True
    assert names["packing-list.csv"] is False


def test_simple_pdf_is_valid_header():
    blob = build_simple_pdf("Fictional note", ["No real patient data."])
    assert blob.startswith(b"%PDF-1.4")
    assert b"%%EOF" in blob
