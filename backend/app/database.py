import logging
import random
import socket
import time
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)


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
    # Sized for the API plus the queue worker threads, which each open short sessions.
    pool_size=10,
    max_overflow=10,
    # Generous enough for a Neon serverless compute to wake up on the first connect.
    connect_args={
        "connect_timeout": 15,
        "prepare_threshold": None,
        # Drop dead TCP sessions rather than blocking a worker on a silent connection.
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
    },
    # Long-lived connections avoid paying reconnect cost on every job.
    pool_recycle=1800,
    pool_timeout=30,
)

_DNS_TTL_SECONDS = 60
_dns_cache: dict[str, tuple[float, list[str]]] = {}


def _ipv4_addresses(host: str) -> list[str]:
    cached = _dns_cache.get(host)
    now = time.monotonic()
    if cached and now - cached[0] < _DNS_TTL_SECONDS:
        return cached[1]
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return []
    addresses = sorted({info[4][0] for info in infos})
    _dns_cache[host] = (now, addresses)
    return addresses


@event.listens_for(engine, "do_connect")
def _prefer_ipv4(_dialect, _conn_rec, _cargs, cparams) -> None:
    """Resolve the database host to IPv4 ourselves and pass it as `hostaddr`.

    libpq resolves with AF_UNSPEC and walks every A/AAAA record in turn. On networks
    where IPv6 egress is silently dropped, each AAAA candidate burns the full
    connect_timeout before failing over, which turns a 2s Neon connect into ~90s.
    Setting `hostaddr` while leaving `host` in place keeps TLS SNI and certificate
    verification pointed at the hostname.
    """
    if not get_settings().db_prefer_ipv4:
        return
    host = cparams.get("host")
    if not host or cparams.get("hostaddr"):
        return
    addresses = _ipv4_addresses(str(host))
    if not addresses:
        # Resolution failed; let libpq try, so a genuinely IPv6-only host still works.
        return
    # Prefer a previously-good address, then rotate if Neon rotates pooler IPs.
    last = _dns_cache.get(f"{host}:last")
    last_ip = last[1][0] if last and last[1] else None
    if last_ip in addresses:
        cparams["hostaddr"] = last_ip
    else:
        cparams["hostaddr"] = random.choice(addresses)


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
