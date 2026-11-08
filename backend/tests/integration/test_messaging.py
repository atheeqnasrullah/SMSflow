from __future__ import annotations

from decimal import Decimal

import httpx
import respx
from sqlalchemy import func, select

from app.core.db import system_session
from app.modules.providers.router import reset_demo_provider
from app.modules.wallet.models import LedgerEntry, Wallet
from tests.conftest import Account, add_live_provider, drain, make_live


async def test_demo_send_lifecycle(owner: Account) -> None:
    r = await owner.post("/sms/send", json={"to": "0771234567", "message": "Hello from the demo gateway"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued" and body["is_demo"] is True and body["cost"] == 0
    await drain()
    msg = (await owner.get(f"/sms/{body['message_id']}")).json()
    assert msg["status"] == "delivered"
    assert [e["status"] for e in msg["events"]][:2] == ["queued", "accepted"]
    bal = (await owner.get("/balance")).json()
    assert bal["demo_credits"] == 499


async def test_demo_magic_numbers(owner: Account) -> None:
    reset_demo_provider(seed=1, delivered_rate=1.0, failed_rate=0.0)
    fail = (await owner.post("/sms/send", json={"to": "+94770000001", "message": "x"})).json()
    timeout = (await owner.post("/sms/send", json={"to": "+94770000002", "message": "x"})).json()
    pending = (await owner.post("/sms/send", json={"to": "+94770000003", "message": "x"})).json()
    await drain()
    assert (await owner.get(f"/sms/{fail['message_id']}")).json()["status"] == "failed"
    t = (await owner.get(f"/sms/{timeout['message_id']}")).json()
    assert t["status"] == "failed" and t["error_code"] == "DEMO_TIMEOUT"
    assert len([e for e in t["events"] if e["status"] == "retry"]) == 4  # 5 attempts total
    assert (await owner.get(f"/sms/{pending['message_id']}")).json()["status"] == "accepted"


async def test_unicode_segments_and_validation(owner: Account) -> None:
    r = await owner.post("/sms/send", json={"to": "0771234567", "message": "ආයුබෝවන්! ඔබේ ඇණවුම තහවුරු කර ඇත."})
    assert r.json()["encoding"] == "UCS2"
    assert (await owner.post("/sms/send", json={"to": "12345", "message": "x"})).json()["error"]["code"] == "invalid_number"
    r = await owner.post("/sms/send", json={"to": "0771234567", "message": "Big sale", "category": "promotional"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "opt_out_required"


async def test_suppressed_number_rejected(owner: Account) -> None:
    await owner.post("/suppressions", json={"phone": "0771234567", "reason": "unsubscribed"})
    r = await owner.post("/sms/send", json={"to": "+94771234567", "message": "hi"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "suppressed"


async def test_live_send_reserves_and_charges(owner: Account) -> None:
    await add_live_provider()
    tid = await make_live(owner, balance=Decimal("10"))
    with respx.mock(assert_all_called=True) as mock:
        mock.post("https://gw.example.com/sms/send").mock(
            return_value=httpx.Response(200, json={"data": {"message_id": "gw-1"}}))
        r = await owner.post("/sms/send", json={"to": "0771234567", "message": "Order shipped", "sender_id": "ACME"})
        assert r.status_code == 202, r.text
        assert r.json()["cost"] == 0.85 and r.json()["is_demo"] is False
        w = (await owner.get("/billing/wallet")).json()
        assert w["reserved"] == 0.85 and w["available"] == 9.15
        await drain()
    msg = (await owner.get(f"/sms/{r.json()['message_id']}")).json()
    assert msg["status"] == "accepted"
    w = (await owner.get("/billing/wallet")).json()
    assert w["balance"] == 9.15 and w["reserved"] == 0
    async with system_session() as s:
        types = (await s.scalars(select(LedgerEntry.type).where(LedgerEntry.tenant_id == tid).order_by(LedgerEntry.created_at))).all()
        assert types == ["adjustment", "reserve", "charge"]
        wallet = await s.scalar(select(Wallet).where(Wallet.tenant_id == tid))
        total = await s.scalar(select(func.sum(LedgerEntry.amount)).where(LedgerEntry.tenant_id == tid))
        assert Decimal(str(total)).quantize(Decimal("0.0001")) == wallet.balance

    # DLR callback through the real HTTP path
    bad = await owner.client.post("/callbacks/dlr/mockgw?token=wrong", json={"message_id": "gw-1", "status": "DELIVRD"})
    assert bad.status_code == 401
    ok = await owner.client.post("/callbacks/dlr/mockgw?token=cb-secret", json={"message_id": "gw-1", "status": "DELIVRD"})
    assert ok.status_code == 200
    await drain()
    assert (await owner.get(f"/sms/{r.json()['message_id']}")).json()["status"] == "delivered"


async def test_live_send_requires_approved_sender_and_funds(owner: Account) -> None:
    await add_live_provider()
    await make_live(owner, balance=Decimal("0.50"))
    r = await owner.post("/sms/send", json={"to": "0771234567", "message": "x", "sender_id": "NOTMINE"})
    assert r.json()["error"]["code"] == "sender_id_not_approved"
    r = await owner.post("/sms/send", json={"to": "0771234567", "message": "x", "sender_id": "ACME"})
    assert r.status_code == 402 and r.json()["error"]["code"] == "insufficient_funds"


async def test_provider_permanent_failure_releases_reservation(owner: Account) -> None:
    await add_live_provider()
    await make_live(owner, balance=Decimal("10"))
    with respx.mock() as mock:
        mock.post("https://gw.example.com/sms/send").mock(return_value=httpx.Response(400, json={"error": "bad"}))
        r = await owner.post("/sms/send", json={"to": "0771234567", "message": "x", "sender_id": "ACME"})
        await drain()
    assert (await owner.get(f"/sms/{r.json()['message_id']}")).json()["status"] == "failed"
    w = (await owner.get("/billing/wallet")).json()
    assert w["balance"] == 10 and w["reserved"] == 0


async def test_idempotency_key(owner: Account) -> None:
    h = {"Idempotency-Key": "order-10045"}
    r1 = await owner.post("/sms/send", json={"to": "0771234567", "message": "Confirmed"}, headers=h)
    r2 = await owner.post("/sms/send", json={"to": "0771234567", "message": "Confirmed"}, headers=h)
    assert r1.json()["message_id"] == r2.json()["message_id"]
    assert r2.headers.get("Idempotent-Replayed") == "true"
    assert (await owner.get("/sms")).json()["total"] == 1
    r3 = await owner.post("/sms/send", json={"to": "0771234567", "message": "Different"}, headers=h)
    assert r3.status_code == 409


async def test_bulk_send_partial_rejections(owner: Account) -> None:
    r = await owner.post("/sms/bulk", json={"messages": [
        {"to": "0771234567", "message": "one"}, {"to": "bad", "message": "two"}, {"to": "0779876543", "message": "three"},
    ]})
    assert r.status_code == 202
    body = r.json()
    assert body["accepted"] == 2 and body["rejected"] == 1
    assert body["results"][1]["error"]["code"] == "invalid_number"
    await drain()
    assert (await owner.get("/sms?status=delivered")).json()["total"] == 2
