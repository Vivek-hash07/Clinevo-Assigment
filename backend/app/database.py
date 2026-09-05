from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _engine_url() -> str:
    url = get_settings().database_url
    # Neon pooler + channel_binding can stall some clients.
    url = url.replace("&channel_binding=require", "").replace("?channel_binding=require&", "?").replace(
        "?channel_binding=require", ""
    )
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


engine = create_engine(
    _engine_url(),
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_recycle=300,
    pool_timeout=20,
    connect_args={"connect_timeout": 20, "prepare_threshold": None},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def ping_db() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
