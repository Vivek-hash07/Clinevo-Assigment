from fastapi import APIRouter

from app.deps import CurrentUser
from app.schemas import SyncMailOut
from app.services.auth import user_to_out

router = APIRouter(prefix="/api/gmail", tags=["gmail"])


@router.post("/sync", response_model=SyncMailOut)
def sync_mail(user: CurrentUser) -> SyncMailOut:
    profile = user_to_out(user)
    if not profile.gmail_connected:
        return SyncMailOut(
            ok=False,
            queued=False,
            gmail_connected=False,
            message="Connect your Google mailbox to sync mail.",
        )
    return SyncMailOut(
        ok=True,
        queued=False,
        gmail_connected=True,
        message="Mailbox is connected. New messages will appear in this queue.",
    )
