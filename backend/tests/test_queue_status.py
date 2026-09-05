from app.constants import QUEUE_STATUSES


def test_queue_statuses_match_plan():
    assert QUEUE_STATUSES == ("pending", "processing", "ready", "reviewed")
