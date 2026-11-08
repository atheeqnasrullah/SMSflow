"""Cross-tenant isolation: tenant B must never read or modify tenant A's data (app level).

When TEST_DATABASE_URL points at PostgreSQL (app role without BYPASSRLS) the same tests also
exercise Row-Level Security; ``test_rls_blocks_unscoped_query`` checks RLS directly.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import tenant_session
from app.modules.contacts.models import Contact
from tests.conftest import Account, drain


async def _seed_a(a: Account) -> dict[str, str]:
    contact = (await a.post("/contacts", json={"phone": "0771111111", "first_name": "A"})).json()
    group = (await a.post("/groups", json={"name": "A group"})).json()
    tpl = (await a.post("/templates", json={"name": "A tpl", "body": "Hello {{first_name}}"})).json()
    camp = (await a.post("/campaigns", json={"name": "A camp", "body": "Hi", "category": "transactional",
                                             "audience": {"group_ids": [group["id"]]}})).json()
    msg = (await a.post("/sms/send", json={"to": "0772222222", "message": "secret A"})).json()
    hook = (await a.post("/developers/webhooks", json={"url": "http://hooks.example.com/a",
                                                       "events": ["message.delivered"]})).json()
    key = (await a.post("/developers/api-keys", json={"name": "A key"})).json()
    await drain()
    return {"contact": contact["id"], "group": group["id"], "template": tpl["id"], "campaign": camp["id"],
            "message": msg["message_id"], "webhook": hook["id"], "api_key": key["id"]}


async def test_tenant_b_cannot_see_or_touch_tenant_a(owner: Account, other_owner: Account) -> None:
    ids = await _seed_a(owner)
    b = other_owner

    # Lists are empty for B
    for url in ("/contacts", "/campaigns", "/sms", "/suppressions"):
        body = (await b.get(url)).json()
        assert body["total"] == 0, url
    for url in ("/groups", "/templates", "/developers/webhooks", "/developers/api-keys", "/sender-ids"):
        assert (await b.get(url)).json() == [], url

    # Direct reads → 404
    for url in (f"/contacts/{ids['contact']}", f"/templates/{ids['template']}", f"/campaigns/{ids['campaign']}",
                f"/sms/{ids['message']}", f"/developers/webhooks/{ids['webhook']}/deliveries"):
        assert (await b.get(url)).status_code == 404, url

    # Writes → 404 and A's data unchanged
    assert (await b.patch(f"/contacts/{ids['contact']}", json={"first_name": "Hacked"})).status_code == 404
    assert (await b.delete(f"/contacts/{ids['contact']}")).status_code == 404
    assert (await b.put(f"/templates/{ids['template']}", json={"name": "x", "body": "x"})).status_code == 404
    assert (await b.post(f"/campaigns/{ids['campaign']}/send")).status_code == 404
    assert (await b.delete(f"/groups/{ids['group']}")).status_code == 404
    assert (await b.delete(f"/developers/api-keys/{ids['api_key']}")).status_code == 404
    assert (await b.post(f"/groups/{ids['group']}/members", json={"contact_ids": [ids["contact"]]})).status_code == 404

    # B cannot add A's contact into B's group
    gb = (await b.post("/groups", json={"name": "B group"})).json()
    r = await b.post(f"/groups/{gb['id']}/members", json={"contact_ids": [ids["contact"]]})
    assert r.json()["added"] == 0

    # B cannot target A's contacts/groups in a campaign
    camp = (await b.post("/campaigns", json={"name": "steal", "body": "Hi", "category": "transactional",
                                             "audience": {"group_ids": [ids["group"]], "contact_ids": [ids["contact"]]}})).json()
    est = (await b.post(f"/campaigns/{camp['id']}/estimate")).json()
    assert est["recipients"] == 0

    a_contact = (await owner.get(f"/contacts/{ids['contact']}")).json()
    assert a_contact["first_name"] == "A"


async def test_tenant_id_in_body_is_ignored(owner: Account, other_owner: Account) -> None:
    a_tid = await owner.tenant_id()
    r = await other_owner.post("/contacts", json={"phone": "0773333333", "tenant_id": str(a_tid)})
    assert r.status_code == 201
    assert (await owner.get("/contacts")).json()["total"] == 0


@pytest.mark.skipif(not settings.is_postgres, reason="RLS requires PostgreSQL")
async def test_rls_blocks_unscoped_query(owner: Account, other_owner: Account) -> None:
    await owner.post("/contacts", json={"phone": "0774444444"})
    b_tid = await other_owner.tenant_id()
    async with tenant_session(b_tid) as s:
        # No WHERE tenant_id clause at all: RLS must still hide A's rows.
        rows = (await s.scalars(select(Contact))).all()
        assert rows == []
    async with tenant_session(uuid.uuid4()) as s:
        assert (await s.scalars(select(Contact))).all() == []
