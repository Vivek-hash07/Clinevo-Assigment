from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.database import ping_db
from app.schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthOut)
def health() -> HealthOut:
    try:
        ping_db()
        db_status = "up"
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc.__class__.__name__}") from exc

    return HealthOut(
        status="ok",
        service="clinevo-api",
        db=db_status,
    )
