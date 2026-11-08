"""Object storage abstraction. Local filesystem implementation; swap for S3-compatible storage
in production by implementing the same three functions (keys are opaque strings)."""

from __future__ import annotations

import uuid
from pathlib import Path

from app.core.config import settings


def _root() -> Path:
    root = Path(settings.storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path(key: str) -> Path:
    p = (_root() / key).resolve()
    if _root() not in p.parents:
        raise ValueError("invalid storage key")
    return p


def put_bytes(prefix: str, filename: str, data: bytes) -> str:
    safe = "".join(c for c in filename if c.isalnum() or c in "._-")[-80:] or "file"
    key = f"{prefix}/{uuid.uuid4().hex}_{safe}"
    p = _path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return key


def get_bytes(key: str) -> bytes:
    return _path(key).read_bytes()


def delete(key: str) -> None:
    p = _path(key)
    if p.exists():
        p.unlink()
