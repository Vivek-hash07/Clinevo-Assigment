from __future__ import annotations

from pathlib import Path

from app.config import get_settings


def _root() -> Path:
    path = Path(get_settings().attachment_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def put_bytes(checksum: str, data: bytes, suffix: str = ".pdf") -> str:
    safe = "".join(ch for ch in checksum if ch.isalnum())
    filename = f"{safe}{suffix}"
    dest = _root() / filename
    if not dest.exists():
        dest.write_bytes(data)
    return filename


def read_bytes(storage_key: str) -> bytes:
    path = _root() / Path(storage_key).name
    if not path.is_file():
        raise FileNotFoundError(storage_key)
    return path.read_bytes()
