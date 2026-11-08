from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.security import api_key_prefix, decrypt_json, encrypt_json, generate_api_key, webhook_signature
from app.modules.contacts.service import csv_safe, parse_rows
from app.modules.payments.service import checkout_hash, notify_signature
from app.shared import phone
from app.shared.sms_segments import analyze
from app.shared.templating import MissingVariable, extract_variables, render
from app.shared.timeutil import in_quiet_hours

FIXTURES = json.loads((Path(__file__).parents[1] / "fixtures" / "sms_segments.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", FIXTURES, ids=[c["name"] for c in FIXTURES])
def test_segments_fixture(case: dict) -> None:
    info = analyze(case["text"])
    assert info.encoding == case["encoding"]
    assert info.length == case["length"]
    assert info.segments == case["segments"]


@pytest.mark.parametrize("raw,expected", [
    ("0771234567", "+94771234567"),
    ("771234567", "+94771234567"),
    ("94771234567", "+94771234567"),
    ("+94 77 123 4567", "+94771234567"),
    ("0094771234567", "+94771234567"),
    ("+447911123456", "+447911123456"),
])
def test_phone_normalize(raw: str, expected: str) -> None:
    assert phone.normalize(raw) == expected


@pytest.mark.parametrize("raw", ["", "12", "abc", "077123"])
def test_phone_invalid(raw: str) -> None:
    with pytest.raises(phone.InvalidPhoneNumber):
        phone.normalize(raw)


def test_lk_mobile() -> None:
    assert phone.is_lk_mobile("+94771234567")
    assert not phone.is_lk_mobile("+94112345678")


def test_templating() -> None:
    body = "Hi {{ first_name }}, order {{order}} ready. {{first_name}}!"
    assert extract_variables(body) == ["first_name", "order"]
    assert render(body, {"first_name": "Kasun", "order": 12}) == "Hi Kasun, order 12 ready. Kasun!"
    with pytest.raises(MissingVariable):
        render(body, {"first_name": "Kasun"})
    assert render(body, {"first_name": "Kasun"}, fallback="-") == "Hi Kasun, order - ready. Kasun!"


def test_api_key_format() -> None:
    full, prefix, digest = generate_api_key(live=True)
    assert full.startswith("sf_live_") and api_key_prefix(full) == prefix
    assert len(digest) == 64
    assert api_key_prefix("not-a-key") is None


def test_encryption_roundtrip() -> None:
    token = encrypt_json({"api_token": "s3cret"})
    assert "s3cret" not in token
    assert decrypt_json(token) == {"api_token": "s3cret"}


def test_webhook_signature_is_hmac_of_timestamp_and_body() -> None:
    import hashlib
    import hmac

    sig = webhook_signature("whsec_x", 1767225600, b'{"a":1}')
    assert sig == "v1=" + hmac.new(b"whsec_x", b'1767225600.{"a":1}', hashlib.sha256).hexdigest()


def test_payhere_hashes() -> None:
    # PayHere formula: UPPER(MD5(merchant_id + order_id + amount(2dp) + currency + UPPER(MD5(secret))))
    import hashlib

    inner = hashlib.md5(b"secret").hexdigest().upper()
    expected = hashlib.md5(f"121ORD11000.00LKR{inner}".encode()).hexdigest().upper()
    assert checkout_hash("121", "ORD1", Decimal("1000"), "LKR", "secret") == expected
    expected_notify = hashlib.md5(f"121ORD11000.00LKR2{inner}".encode()).hexdigest().upper()
    assert notify_signature("121", "ORD1", "1000.00", "LKR", "2", "secret") == expected_notify


def test_quiet_hours_colombo() -> None:
    # 16:00 UTC = 21:30 Colombo → quiet; 05:00 UTC = 10:30 Colombo → not quiet
    assert in_quiet_hours(datetime(2026, 1, 1, 16, 0, tzinfo=timezone.utc), 21, 8)
    assert not in_quiet_hours(datetime(2026, 1, 1, 5, 0, tzinfo=timezone.utc), 21, 8)


def test_csv_injection_escaped() -> None:
    assert csv_safe("=HYPERLINK()") == "'=HYPERLINK()"
    assert csv_safe("+94771234567") == "'+94771234567"
    assert csv_safe("Kasun") == "Kasun"


def test_parse_csv_aliases_and_headerless() -> None:
    rows = list(parse_rows("c.csv", b"Mobile,First Name,City\n0771234567,Kasun,Kandy\n"))
    assert rows == [{"phone": "0771234567", "first_name": "Kasun", "city": "Kandy"}]
    rows = list(parse_rows("c.csv", b"0771234567\n0779876543\n"))
    assert [r["phone"] for r in rows] == ["0771234567", "0779876543"]
