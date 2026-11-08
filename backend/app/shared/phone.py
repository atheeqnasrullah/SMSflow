"""Phone number normalisation (E.164) with Sri Lankan defaults."""

from __future__ import annotations

import re

import phonenumbers

from app.core.config import settings

LK_MOBILE_RE = re.compile(r"^\+947[0-9]{8}$")


class InvalidPhoneNumber(ValueError):
    pass


def normalize(raw: str, default_region: str | None = None) -> str:
    """Return E.164 form or raise :class:`InvalidPhoneNumber`."""
    if raw is None:
        raise InvalidPhoneNumber("empty")
    candidate = re.sub(r"[\s\-().]", "", str(raw).strip())
    if candidate.startswith("00"):
        candidate = "+" + candidate[2:]
    # Common Sri Lankan forms: 0771234567, 771234567, 94771234567
    if re.fullmatch(r"7[0-9]{8}", candidate):
        candidate = "+94" + candidate
    elif re.fullmatch(r"94[0-9]{9}", candidate):
        candidate = "+" + candidate
    try:
        parsed = phonenumbers.parse(candidate, default_region or settings.default_country)
    except phonenumbers.NumberParseException as exc:
        raise InvalidPhoneNumber(str(exc)) from exc
    if not phonenumbers.is_valid_number(parsed):
        raise InvalidPhoneNumber(f"invalid number: {raw}")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def try_normalize(raw: str | None) -> str | None:
    try:
        return normalize(raw or "")
    except InvalidPhoneNumber:
        return None


def is_lk_mobile(e164: str) -> bool:
    return bool(LK_MOBILE_RE.match(e164))


def mask(e164: str) -> str:
    return e164[:-4].rstrip() + "****" if len(e164) > 6 else "****"
