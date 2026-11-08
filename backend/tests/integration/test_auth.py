from __future__ import annotations

import httpx

from tests.conftest import PASSWORD, register


async def test_register_me_and_workspace(client: httpx.AsyncClient) -> None:
    acc = await register(client, "kasun@example.com", business="Kasun Stores")
    r = await acc.get("/auth/me")
    assert r.status_code == 200
    me = r.json()
    assert me["email"] == "kasun@example.com"
    assert me["role"] == "owner"
    assert me["workspaces"][0]["name"] == "Kasun Stores"
    assert me["workspaces"][0]["mode"] == "demo"
    assert "billing:manage" in me["permissions"]
    bal = (await acc.get("/balance")).json()
    assert bal["demo_credits"] == 500 and bal["balance"] == 0


async def test_duplicate_email_rejected(client: httpx.AsyncClient) -> None:
    await register(client, "dup@example.com")
    r = await client.post("/auth/register", json={"email": "DUP@example.com", "password": PASSWORD,
                                                  "full_name": "X Y", "business_name": "Biz"})
    assert r.status_code == 409


async def test_weak_password_rejected(client: httpx.AsyncClient) -> None:
    r = await client.post("/auth/register", json={"email": "w@example.com", "password": "aaaaaaaaaaaa",
                                                  "full_name": "X Y", "business_name": "Biz"})
    assert r.status_code == 422


async def test_login_lockout(client: httpx.AsyncClient) -> None:
    await register(client, "lock@example.com")
    for _ in range(5):
        r = await client.post("/auth/login", json={"email": "lock@example.com", "password": "wrong-password-1"})
        assert r.status_code == 401
    r = await client.post("/auth/login", json={"email": "lock@example.com", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "account_locked"


async def test_refresh_rotation_and_reuse_detection(client: httpx.AsyncClient) -> None:
    await register(client, "rot@example.com")
    r = await client.post("/auth/login", json={"email": "rot@example.com", "password": PASSWORD})
    first_cookie = r.cookies.get("sf_refresh")
    assert first_cookie
    client.cookies.clear()  # send exactly the cookie under test, not the jar's latest
    r2 = await client.post("/auth/refresh", cookies={"sf_refresh": first_cookie})
    assert r2.status_code == 200
    second_cookie = r2.cookies.get("sf_refresh")
    assert second_cookie and second_cookie != first_cookie
    # Re-using the rotated token revokes the whole family …
    client.cookies.clear()
    r3 = await client.post("/auth/refresh", cookies={"sf_refresh": first_cookie})
    assert r3.status_code == 401 and r3.json()["error"]["code"] == "refresh_reuse"
    # … including the newest token.
    client.cookies.clear()
    r4 = await client.post("/auth/refresh", cookies={"sf_refresh": second_cookie})
    assert r4.status_code == 401


async def test_refresh_requires_csrf_header(client: httpx.AsyncClient) -> None:
    await register(client, "csrf@example.com")
    r = await client.post("/auth/login", json={"email": "csrf@example.com", "password": PASSWORD})
    cookie = r.cookies.get("sf_refresh")
    r2 = await client.post("/auth/refresh", cookies={"sf_refresh": cookie}, headers={"X-Requested-With": ""})
    assert r2.status_code == 403


async def test_invitation_flow_and_rbac(client: httpx.AsyncClient) -> None:
    owner = await register(client, "boss@example.com")
    r = await owner.post("/workspace/invitations", json={"email": "viewer@example.com", "role": "viewer"})
    assert r.status_code == 201
    # Fetch the raw token by reading the queued email task.
    from app.workers.dispatch import inline_queue

    email_task = [kw for _, _, name, kw in inline_queue._heap if name == "email.send" and kw["to"] == "viewer@example.com"][0]
    token = email_task["text"].split("token=")[1].strip()
    r = await client.post("/auth/accept-invitation", json={"token": token, "full_name": "Vee Viewer", "password": PASSWORD})
    assert r.status_code == 200, r.text
    viewer_h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await client.get("/auth/me", headers=viewer_h)).json()
    assert me["role"] == "viewer"
    # Viewer can read reports but cannot create contacts or send.
    assert (await client.get("/reports/overview", headers=viewer_h)).status_code == 200
    assert (await client.post("/contacts", json={"phone": "0771234567"}, headers=viewer_h)).status_code == 403
    assert (await client.post("/sms/send", json={"to": "0771234567", "message": "hi"}, headers=viewer_h)).status_code == 403
    members = (await owner.get("/workspace/members")).json()
    assert {m["role"] for m in members} == {"owner", "viewer"}
