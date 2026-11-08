"""Password hashing, JWTs, opaque tokens, API-key hashing and AES-GCM encryption."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_ph = PasswordHasher()  # Argon2id with library defaults


# --- Passwords --------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


# --- JWT access tokens -------------------------------------------------------------------
def _signing_key() -> str:
    if settings.jwt_algorithm == "HS256":
        return settings.jwt_secret
    if not settings.jwt_private_key:
        raise RuntimeError("JWT_PRIVATE_KEY is required for asymmetric JWT algorithms")
    return settings.jwt_private_key


def _verify_key() -> str:
    if settings.jwt_algorithm == "HS256":
        return settings.jwt_secret
    if not settings.jwt_public_key:
        raise RuntimeError("JWT_PUBLIC_KEY is required for asymmetric JWT algorithms")
    return settings.jwt_public_key


def create_access_token(
    *, user_id: uuid.UUID, tenant_id: uuid.UUID | None, role: str | None, is_platform_admin: bool
) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    ttl = settings.access_token_ttl_minutes * 60
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "tid": str(tenant_id) if tenant_id else None,
        "role": role,
        "pa": is_platform_admin,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "jti": secrets.token_hex(8),
        "typ": "access",
    }
    return jwt.encode(claims, _signing_key(), algorithm=settings.jwt_algorithm), ttl


def decode_access_token(token: str) -> dict[str, Any]:
    claims = jwt.decode(token, _verify_key(), algorithms=[settings.jwt_algorithm])
    if claims.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return claims


# --- Opaque tokens (refresh, email verification, reset, invitations) ------------------
def new_opaque_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# --- API keys --------------------------------------------------------------------------
def generate_api_key(live: bool) -> tuple[str, str, str]:
    """Return (full_key, prefix, sha256_hash). Format: ``sf_{live|test}_{prefix8}_{secret}``."""
    kind = "live" if live else "test"
    prefix_part = secrets.token_hex(4)
    secret = secrets.token_urlsafe(24).replace("_", "x").replace("-", "y")
    prefix = f"sf_{kind}_{prefix_part}"
    full = f"{prefix}_{secret}"
    return full, prefix, sha256_hex(full)


def api_key_prefix(full_key: str) -> str | None:
    parts = full_key.split("_")
    if len(parts) != 4 or parts[0] != "sf" or parts[1] not in ("live", "test"):
        return None
    return "_".join(parts[:3])


# --- OTP --------------------------------------------------------------------------------
def hash_otp(code: str, salt: str) -> str:
    return hmac.new(settings.otp_hash_secret.encode(), f"{salt}:{code}".encode(), "sha256").hexdigest()


def generate_numeric_code(length: int) -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


# --- Symmetric encryption (AES-GCM) ------------------------------------------------------
def _aes_key() -> bytes:
    key = base64.b64decode(settings.encryption_key)
    if len(key) not in (16, 24, 32):
        raise RuntimeError("ENCRYPTION_KEY must be base64 of 16/24/32 bytes")
    return key


def encrypt_str(plaintext: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_aes_key()).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt_str(token: str) -> str:
    raw = base64.b64decode(token)
    return AESGCM(_aes_key()).decrypt(raw[:12], raw[12:], None).decode()


def encrypt_json(data: dict[str, Any]) -> str:
    return encrypt_str(json.dumps(data))


def decrypt_json(token: str | None) -> dict[str, Any]:
    return json.loads(decrypt_str(token)) if token else {}


# --- Webhook signatures -------------------------------------------------------------------
def webhook_signature(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"v1={mac}"
