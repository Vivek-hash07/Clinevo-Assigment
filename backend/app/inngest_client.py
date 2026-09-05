from __future__ import annotations

import logging

import inngest

from app.config import get_settings

_settings = get_settings()

inngest_client = inngest.Inngest(
    app_id=_settings.inngest_app_id,
    is_production=_settings.app_env == "production",
    event_key=_settings.inngest_event_key or None,
    signing_key=_settings.inngest_signing_key or None,
    logger=logging.getLogger("inngest"),
)
