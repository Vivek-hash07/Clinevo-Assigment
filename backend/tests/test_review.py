from types import SimpleNamespace

import pytest

from app.constants import CAT_ICSR, OVERRIDE_REASON_MIN_CHARS
from app.models import ExtractedField
from app.schemas import ReviewRequest
from app.services.review import (
    ReviewError,
    can_review_status,
    field_label,
    grouped_fields,
    latest_field_reviews,
    validate_review_payload,
)


def test_override_requires_reason():
    with pytest.raises(ReviewError, match="Override reason is required"):
        validate_review_payload(
            ReviewRequest(action="override", field="patient.age", value="42", reason="short"),
            current_value="Not stated",
        )


def test_override_requires_value_change():
    reason = "x" * OVERRIDE_REASON_MIN_CHARS
    with pytest.raises(ReviewError, match="must differ"):
        validate_review_payload(
            ReviewRequest(action="override", field="patient.age", value="42", reason=reason),
            current_value="42",
        )


def test_override_trims_and_accepts_valid_change():
    reason = "Confirmed from the PDF header"
    got = validate_review_payload(
        ReviewRequest(action="override", field=" patient.age ", value="  61  ", reason=f"  {reason}  "),
        current_value="Not stated",
    )
    assert got.action == "override"
    assert got.field == "patient.age"
    assert got.value == "61"
    assert got.reason == reason


def test_accept_does_not_need_reason():
    got = validate_review_payload(ReviewRequest(action="accept", field="patient.age"))
    assert got.action == "accept"
    assert got.field == "patient.age"
    assert got.value is None


def test_accept_requires_field():
    with pytest.raises(ReviewError, match="Field is required"):
        validate_review_payload(ReviewRequest(action="accept"))


def test_complete_rejects_field_payload():
    with pytest.raises(ReviewError, match="does not take a field"):
        validate_review_payload(ReviewRequest(action="complete", field="patient.age"))


def test_only_ready_or_reviewed_can_be_reviewed():
    assert can_review_status("ready")
    assert can_review_status("reviewed")
    assert not can_review_status("pending")
    assert not can_review_status("processing")


def test_field_labels_and_groups():
    assert field_label("patient.age") == "Patient age"
    assert field_label("patient.weight") == "Patient weight"
    fields = [
        ExtractedField(field="patient.age", value="61", confidence=0.9),
        ExtractedField(field="pqc.defect", value="cracked vial", confidence=0.8),
        ExtractedField(field="custom.note", value="hello", confidence=0.1),
    ]
    groups = grouped_fields(fields)
    ids = [item[0] for item in groups]
    assert ids == ["icsr", "pqc", "other"]
    assert groups[0][1] == CAT_ICSR


def test_latest_field_review_wins():
    first = SimpleNamespace(action="accept", field_name="patient.age", created_at=1, reason="ok")
    second = SimpleNamespace(action="override", field_name="patient.age", created_at=2, reason="fix")
    latest = latest_field_reviews([first, second])  # type: ignore[arg-type]
    assert latest["patient.age"].action == "override"
