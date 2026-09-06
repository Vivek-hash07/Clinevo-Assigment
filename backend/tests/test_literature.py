from app.constants import SOURCE_SPLIT, SOURCE_UPLOAD
from app.models import Message
from app.services.literature import _cases_from_payload, should_auto_screen


def test_cases_from_payload_drops_empty():
    cases = _cases_from_payload(
        {
            "identifiable_patient_case": True,
            "cases": [
                {"index": 1, "summary": "Hives", "excerpt": "Jordan Hale developed hives", "source_ref": "pdf:x:page:1"},
                {"index": 2, "summary": "", "excerpt": ""},
                "bad",
            ],
        }
    )
    assert len(cases) == 1
    assert cases[0]["index"] == 1
    assert "hives" in cases[0]["excerpt"]


def test_auto_screen_upload_not_split():
    upload = Message(source=SOURCE_UPLOAD, parent_message_id=None)
    child = Message(source=SOURCE_SPLIT, parent_message_id="abc")
    gmail = Message(source="gmail", parent_message_id=None)
    assert should_auto_screen(upload) is True
    assert should_auto_screen(child) is False
    assert should_auto_screen(gmail) is False
