from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal

import httpx
import respx
from sqlalchemy import select

from app.core.db import system_session, utcnow
from app.modules.campaigns.models import Campaign
from app.modules.campaigns.service import dispatch_due
from app.modules.messaging.models import Message
from app.modules.payments.service import notify_signature
from app.modules.providers.router import reset_demo_provider
from tests.conftest import Account, add_live_provider, drain, make_live


async def _audience(acc: Account, n: int = 3) -> str:
    g = (await acc.post("/groups", json={"name": "VIP"})).json()
    for i in range(n):
        await acc.post("/contacts", json={"phone": f"07712340{i:02d}", "first_name": f"C{i}", "consent_status": "granted",
                                          "attributes": {"city": "Kandy"}, "group_ids": [g["id"]]})
    # one without consent: skipped for promotional campaigns
    await acc.post("/contacts", json={"phone": "0779999999", "first_name": "NoConsent", "group_ids": [g["id"]]})
    return g["id"]


async def test_demo_campaign_end_to_end(owner: Account) -> None:
    gid = await _audience(owner)
    camp = (await owner.post("/campaigns", json={
        "name": "Weekend sale", "body": "Hi {{first_name}}, 20% off in {{city}}! Reply STOP to opt out.",
        "category": "promotional", "audience": {"group_ids": [gid], "numbers": ["0771234000", "bad-number"]},
    })).json()
    assert camp["status"] == "draft" and camp["is_demo"] is True
    est = (await owner.post(f"/campaigns/{camp['id']}/estimate")).json()
    assert est["recipients"] == 3  # the raw number duplicates C0; NoConsent + invalid are skipped
    assert est["skipped"]["no_consent"] == 1 and est["skipped"]["invalid"] == 1 and est["skipped"]["duplicates"] == 1
    assert est["sample"][0]["body"].startswith("Hi C0, 20% off in Kandy!")

    r = await owner.post(f"/campaigns/{camp['id']}/send")
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "processing"
    await drain()
    done = (await owner.get(f"/campaigns/{camp['id']}")).json()
    assert done["status"] == "completed"
    assert done["stats"]["delivered"] == 3 and done["stats"]["delivery_rate"] == 100.0
    assert (await owner.get("/balance")).json()["demo_credits"] == 497
    report = (await owner.get("/reports/overview")).json()
    assert report["delivered"] == 3 and report["by_source"]["campaign"] == 3


async def test_campaign_rules(owner: Account) -> None:
    gid = await _audience(owner, 1)
    camp = (await owner.post("/campaigns", json={"name": "No optout", "body": "Sale!", "category": "promotional",
                                                 "audience": {"group_ids": [gid]}})).json()
    r = await owner.post(f"/campaigns/{camp['id']}/send")
    assert r.json()["error"]["code"] == "opt_out_required"
    empty = (await owner.post("/campaigns", json={"name": "Empty", "body": "Hi", "category": "transactional"})).json()
    assert (await owner.post(f"/campaigns/{empty['id']}/send")).status_code == 422
    assert (await owner.post("/campaigns", json={"name": "x", "body": "y", "recurrence": "nonsense"})).status_code == 422


async def test_scheduled_live_campaign_reserve_cancel_release(owner: Account) -> None:
    await add_live_provider()
    await make_live(owner, balance=Decimal("10"))
    gid = await _audience(owner, 2)
    camp = (await owner.post("/campaigns", json={"name": "Later", "body": "Reminder for {{first_name}}",
                                                 "category": "transactional", "sender": "ACME",
                                                 "audience": {"group_ids": [gid]}})).json()
    when = (utcnow() + timedelta(days=1)).isoformat()
    r = await owner.post(f"/campaigns/{camp['id']}/schedule", json={"scheduled_at": when})
    assert r.status_code == 200, r.text
    # 3 recipients (transactional ignores consent) × 1 segment × 0.85
    assert r.json()["estimated_cost"] == 2.55
    w = (await owner.get("/billing/wallet")).json()
    assert w["reserved"] == 2.55 and w["available"] == 7.45
    r = await owner.post(f"/campaigns/{camp['id']}/cancel")
    assert r.json()["status"] == "cancelled"
    w = (await owner.get("/billing/wallet")).json()
    assert w["reserved"] == 0 and w["balance"] == 10


async def test_due_campaign_dispatch_and_live_charges(owner: Account) -> None:
    await add_live_provider()
    await make_live(owner, balance=Decimal("10"))
    gid = await _audience(owner, 2)
    camp = (await owner.post("/campaigns", json={"name": "Due", "body": "Hello {{first_name}}", "category": "transactional",
                                                 "sender": "ACME", "audience": {"group_ids": [gid]}})).json()
    await owner.post(f"/campaigns/{camp['id']}/schedule", json={"scheduled_at": (utcnow() + timedelta(hours=1)).isoformat()})
    async with system_session() as s:
        c = await s.get(Campaign, __import__("uuid").UUID(camp["id"]))
        assert c is not None
        c.scheduled_at = utcnow() - timedelta(minutes=1)
        await s.commit()
    with respx.mock() as mock:
        counter = {"n": 0}

        def _ok(request: httpx.Request) -> httpx.Response:
            counter["n"] += 1
            return httpx.Response(200, json={"data": {"message_id": f"gw-{counter['n']}"}})

        mock.post("https://gw.example.com/sms/send").mock(side_effect=_ok)
        assert await dispatch_due() == 1
        await drain()
    done = (await owner.get(f"/campaigns/{camp['id']}")).json()
    assert done["status"] == "completed" and done["stats"]["accepted"] == 3
    w = (await owner.get("/billing/wallet")).json()
    assert w["balance"] == 7.45 and w["reserved"] == 0


async def test_pause_resume(owner: Account) -> None:
    gid = await _audience(owner, 3)
    camp = (await owner.post("/campaigns", json={"name": "P", "body": "Hi", "category": "transactional",
                                                 "audience": {"group_ids": [gid]}})).json()
    await owner.post(f"/campaigns/{camp['id']}/send")
    assert (await owner.post(f"/campaigns/{camp['id']}/pause")).json()["status"] == "paused"
    await drain()
    paused = (await owner.get(f"/campaigns/{camp['id']}")).json()
    assert paused["status"] == "paused" and paused["stats"].get("delivered", 0) == 0
    assert (await owner.post(f"/campaigns/{camp['id']}/resume")).json()["status"] == "processing"
    await drain()
    assert (await owner.get(f"/campaigns/{camp['id']}")).json()["status"] == "completed"


async def test_payhere_topup_idempotent(owner: Account, client: httpx.AsyncClient) -> None:
    pkg = (await owner.get("/billing/packages")).json()[0]
    co = (await owner.post("/billing/checkout", json={"package_id": pkg["id"]})).json()
    assert co["checkout"]["hash"] and co["checkout"]["amount"] == "1000.00"
    order = co["order_id"]
    form = {"merchant_id": "1211149", "order_id": order, "payment_id": "PH123", "payhere_amount": "1000.00",
            "payhere_currency": "LKR", "status_code": "2"}
    # Bad signature → ignored
    await client.post("/callbacks/payhere/notify", data={**form, "md5sig": "DEADBEEF"})
    assert (await owner.get(f"/billing/payments/{order}")).json()["status"] == "pending"
    form["md5sig"] = notify_signature("1211149", order, "1000.00", "LKR", "2", "test-merchant-secret")
    for _ in range(3):  # duplicate notifications must credit once
        assert (await client.post("/callbacks/payhere/notify", data=form)).status_code == 200
    p = (await owner.get(f"/billing/payments/{order}")).json()
    assert p["status"] == "completed" and p["invoice_number"].startswith("INV-")
    w = (await owner.get("/billing/wallet")).json()
    assert w["balance"] == 1050.0  # credits + bonus
    ledger = (await owner.get("/billing/ledger")).json()
    assert sorted(e["type"] for e in ledger["items"]) == ["bonus", "topup"]
    assert (await owner.get(f"/billing/invoices/{p['invoice_id']}")).status_code == 200
    # Amount mismatch is rejected
    co2 = (await owner.post("/billing/checkout", json={"package_id": pkg["id"]})).json()
    bad = {**form, "order_id": co2["order_id"], "payhere_amount": "1.00"}
    bad["md5sig"] = notify_signature("1211149", co2["order_id"], "1.00", "LKR", "2", "test-merchant-secret")
    await client.post("/callbacks/payhere/notify", data=bad)
    assert (await owner.get(f"/billing/payments/{co2['order_id']}")).json()["status"] == "failed"
    assert (await owner.get("/billing/wallet")).json()["balance"] == 1050.0


async def test_api_key_scopes_and_revocation(owner: Account, client: httpx.AsyncClient) -> None:
    created = (await owner.post("/developers/api-keys", json={"name": "shop", "scopes": ["sms:send"]})).json()
    key = created["key"]
    assert key.startswith("sf_test_")  # demo workspaces get test keys
    h = {"Authorization": f"Bearer {key}"}
    r = await client.post("/sms/send", json={"to": "0771234567", "message": "via api"}, headers=h)
    assert r.status_code == 202 and r.json()["is_demo"] is True
    assert (await client.get("/sms", headers=h)).status_code == 403  # no sms:read scope
    assert (await client.get("/contacts", headers=h)).status_code == 403
    await drain()
    logs = (await owner.get("/developers/request-logs")).json()
    assert logs["total"] >= 1
    await owner.delete(f"/developers/api-keys/{created['id']}")
    assert (await client.post("/sms/send", json={"to": "0771234567", "message": "x"}, headers=h)).status_code == 401
    assert (await client.get("/balance", headers={"Authorization": "Bearer sf_live_nope_nope"})).status_code == 401


async def test_rate_limit(owner: Account, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core.config import settings

    monkeypatch.setattr(settings, "rate_limit_per_second", 3)
    codes = [(await owner.get("/templates")).status_code for _ in range(6)]
    assert 429 in codes
    r = await owner.get("/templates")
    if r.status_code == 429:
        assert r.headers["Retry-After"] == "1"


async def test_otp_send_and_verify(owner: Account) -> None:
    r = await owner.post("/otp/send", json={"to": "0771234567", "brand": "AcmeApp"})
    assert r.status_code == 202, r.text
    otp = r.json()
    async with system_session() as s:
        body = await s.scalar(select(Message.body).where(Message.id == __import__("uuid").UUID(otp["message_id"])))
    assert body and "AcmeApp" in body
    code = "".join(ch for ch in body.split("is ")[1].split(".")[0] if ch.isdigit())
    assert len(code) == 6
    wrong = (await owner.post("/otp/verify", json={"to": "0771234567", "code": "000000" if code != "000000" else "111111"})).json()
    assert wrong == {"verified": False, "reason": "invalid_code"}
    ok = (await owner.post("/otp/verify", json={"to": "+94771234567", "code": code})).json()
    assert ok == {"verified": True, "reason": "verified"}
    again = (await owner.post("/otp/verify", json={"to": "0771234567", "code": code})).json()
    assert again["verified"] is False
    # per-number throttle (3 per 10 min)
    await owner.post("/otp/send", json={"to": "0771234567"})
    await owner.post("/otp/send", json={"to": "0771234567"})
    assert (await owner.post("/otp/send", json={"to": "0771234567"})).status_code == 429


async def test_webhook_delivery_is_signed(owner: Account) -> None:
    reset_demo_provider(seed=3, delivered_rate=1.0, failed_rate=0.0)
    created = (await owner.post("/developers/webhooks", json={"url": "https://hooks.example.com/sf",
                                                              "events": ["message.delivered"]})).json()
    secret = created["secret"]
    received: list[httpx.Request] = []
    with respx.mock() as mock:
        mock.post("https://hooks.example.com/sf").mock(side_effect=lambda req: received.append(req) or httpx.Response(200))
        await owner.post("/sms/send", json={"to": "0771234567", "message": "hook me"})
        await drain()
    assert len(received) == 1
    req = received[0]
    assert req.headers["SMSFlow-Event"] == "message.delivered"
    ts = req.headers["SMSFlow-Timestamp"]
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + req.content, hashlib.sha256).hexdigest()
    assert req.headers["SMSFlow-Signature"] == f"v1={expected}"
    assert json.loads(req.content)["data"]["status"] == "delivered"
    deliveries = (await owner.get(f"/developers/webhooks/{created['id']}/deliveries")).json()
    assert deliveries["items"][0]["status"] == "succeeded"


async def test_webhook_retries_then_fails(owner: Account) -> None:
    created = (await owner.post("/developers/webhooks", json={"url": "https://hooks.example.com/down",
                                                              "events": ["message.accepted"]})).json()
    with respx.mock() as mock:
        route = mock.post("https://hooks.example.com/down").mock(return_value=httpx.Response(500))
        await owner.post("/sms/send", json={"to": "0771234567", "message": "x"})
        await drain()
        assert route.call_count == 7  # first try + 6 retries
    d = (await owner.get(f"/developers/webhooks/{created['id']}/deliveries")).json()["items"][0]
    assert d["status"] == "failed" and d["attempt"] == 7


async def test_admin_console(admin: Account, owner: Account) -> None:
    tid = await owner.tenant_id()
    assert (await owner.get("/admin/tenants")).status_code == 403
    tenants = (await admin.get("/admin/tenants")).json()
    assert tenants["total"] == 1
    r = await admin.post(f"/admin/tenants/{tid}/wallet-adjustments", json={"amount": "250", "type": "bonus", "reason": "Launch promo"})
    assert r.json()["balance"] == 250
    await owner.post("/sender-ids", json={"value": "ACMELK", "purpose": "OTP"})
    pending = (await admin.get("/admin/sender-ids")).json()
    assert pending[0]["value"] == "ACMELK"
    await admin.post(f"/admin/sender-ids/{pending[0]['id']}/review", json={"approve": True})
    assert (await owner.get("/sender-ids")).json()[0]["status"] == "approved"
    await admin.patch(f"/admin/tenants/{tid}", json={"status": "suspended", "suspended_reason": "abuse"})
    r = await owner.post("/sms/send", json={"to": "0771234567", "message": "x"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "tenant_suspended"
    logs = (await admin.get("/admin/audit-logs?action=admin.")).json()
    assert {entry["action"] for entry in logs} >= {"admin.wallet_adjusted", "admin.sender_id_reviewed", "admin.tenant_updated"}
    assert (await admin.get("/admin/stats")).status_code == 200
    assert (await admin.get("/admin/abuse")).status_code == 200
    assert (await admin.get("/admin/revenue")).status_code == 200


async def test_contact_import(owner: Account) -> None:
    g = (await owner.post("/groups", json={"name": "Imported"})).json()
    csv_data = "phone,first_name,city\n0771234567,Kasun,Kandy\n0771234567,Dup,Galle\nnotaphone,Bad,X\n0779876543,Ayesha,Galle\n"
    r = await owner.post("/contacts/imports", files={"file": ("list.csv", csv_data.encode(), "text/csv")},
                         data={"group_id": g["id"], "consent_status": "granted"})
    assert r.status_code == 202, r.text
    await drain()
    job = (await owner.get(f"/contacts/imports/{r.json()['id']}")).json()
    assert (job["status"], job["imported"], job["duplicates"], job["invalid"]) == ("completed", 2, 1, 1)
    assert job["has_error_report"]
    contacts = (await owner.get(f"/contacts?group_id={g['id']}")).json()
    assert contacts["total"] == 2
    assert contacts["items"][0]["attributes"]["city"] in ("Kandy", "Galle")
    export = await owner.get("/contacts/export")
    assert "'+94771234567" in export.text  # formula-injection safe
