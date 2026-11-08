"""Configurable JSON/HTTP adapter used for Sri Lankan aggregators (SMSlenz, Text.lk, …).

Local aggregators expose broadly similar REST APIs (bearer/API-token auth, JSON send endpoint
returning a message id, DLR webhooks). The exact field names differ, so each adapter is a thin
subclass declaring its defaults; everything can be overridden from the encrypted provider config.

IMPORTANT: verify the default field mappings against the provider's current API documentation
and record provider responses as contract-test fixtures (tests/contract) before going live.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.modules.providers.base import (
    BaseHttpProvider,
    DeliveryReport,
    DlrRequest,
    OutboundSms,
    ProviderBalance,
    SendResult,
)


def _dig(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


class GenericHttpProvider(BaseHttpProvider):
    code = "generic"
    defaults: dict[str, Any] = {
        "base_url": "",
        "send_path": "/sms/send",
        "auth_header": "Authorization",
        "auth_scheme": "Bearer",
        "to_field": "to",
        "to_format": "e164",  # e164 | e164_no_plus | local
        "sender_field": "sender_id",
        "body_field": "message",
        "message_id_path": "data.message_id",
        "success_path": None,  # e.g. "status" with success_values
        "success_values": ["success", "ok", True],
        "balance_path": "/balance",
        "balance_value_path": "data.balance",
        "dlr_id_field": "message_id",
        "dlr_status_field": "status",
        "dlr_status_map": {
            "delivered": "delivered",
            "DELIVRD": "delivered",
            "failed": "undelivered",
            "undelivered": "undelivered",
            "UNDELIV": "undelivered",
            "EXPIRED": "undelivered",
            "REJECTD": "undelivered",
            "sent": "accepted",
        },
    }

    def __init__(self, config: dict[str, Any], *, provider_code: str | None = None) -> None:
        super().__init__({**self.defaults, **config}, provider_code=provider_code)

    def _headers(self) -> dict[str, str]:
        c = self.config
        token = c.get("api_token") or c.get("api_key") or ""
        value = f"{c['auth_scheme']} {token}".strip() if c.get("auth_scheme") else token
        return {c["auth_header"]: value, "Accept": "application/json"}

    def _format_to(self, e164: str) -> str:
        fmt = self.config["to_format"]
        if fmt == "e164_no_plus":
            return e164.lstrip("+")
        if fmt == "local" and e164.startswith("+94"):
            return "0" + e164[3:]
        return e164

    async def send(self, msg: OutboundSms) -> SendResult:
        c = self.config
        payload = {
            c["to_field"]: self._format_to(msg.to),
            c["sender_field"]: msg.sender,
            c["body_field"]: msg.body,
        }
        try:
            async with httpx.AsyncClient(base_url=c["base_url"], timeout=self.timeout) as client:
                resp = await client.post(c["send_path"], json=payload, headers=self._headers())
        except httpx.TimeoutException:
            return SendResult("retryable_error", error_code="TIMEOUT")
        except httpx.HTTPError as exc:
            return SendResult("retryable_error", error_code="NETWORK", error_message=str(exc))
        try:
            body = resp.json()
        except ValueError:
            body = {"text": resp.text[:500]}
        if resp.status_code >= 300:
            return SendResult(self.classify_http(resp.status_code), error_code=str(resp.status_code), raw=body)
        if c.get("success_path") and _dig(body, c["success_path"]) not in c["success_values"]:
            return SendResult("permanent_error", error_code="PROVIDER_REJECTED", raw=body)
        mid = _dig(body, c["message_id_path"])
        if not mid:
            return SendResult("permanent_error", error_code="NO_MESSAGE_ID", raw=body)
        return SendResult("accepted", provider_message_id=str(mid), raw=body)

    async def get_balance(self) -> ProviderBalance:
        from decimal import Decimal, InvalidOperation

        c = self.config
        async with httpx.AsyncClient(base_url=c["base_url"], timeout=self.timeout) as client:
            resp = await client.get(c["balance_path"], headers=self._headers())
        body = resp.json() if resp.status_code == 200 else {}
        raw_value = _dig(body, c["balance_value_path"])
        try:
            amount = Decimal(str(raw_value)) if raw_value is not None else None
        except InvalidOperation:
            amount = None
        return ProviderBalance(amount=amount, currency="LKR", raw=body)

    def parse_dlr(self, request: DlrRequest) -> list[DeliveryReport]:
        c = self.config
        items = request.json if isinstance(request.json, list) else [request.json or request.form or request.query]
        out: list[DeliveryReport] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            mid = item.get(c["dlr_id_field"])
            raw_status = str(item.get(c["dlr_status_field"], ""))
            if not mid:
                continue
            status = c["dlr_status_map"].get(raw_status, c["dlr_status_map"].get(raw_status.lower(), "unknown"))
            out.append(DeliveryReport(provider_message_id=str(mid), status=status, raw=item))
        return out


class SmslenzProvider(GenericHttpProvider):
    code = "smslenz"
    defaults = {
        **GenericHttpProvider.defaults,
        "base_url": "https://smslenz.lk/api",
        "send_path": "/send-sms",
        "to_field": "contact",
        "to_format": "e164",
        "sender_field": "sender_id",
        "body_field": "message",
        "message_id_path": "data.campaign_id",
    }


class TextlkProvider(GenericHttpProvider):
    code = "textlk"
    defaults = {
        **GenericHttpProvider.defaults,
        "base_url": "https://app.text.lk/api/v3",
        "send_path": "/sms/send",
        "to_field": "recipient",
        "to_format": "e164_no_plus",
        "sender_field": "sender_id",
        "body_field": "message",
        "message_id_path": "data.uid",
        "success_path": "status",
        "success_values": ["success"],
        "balance_path": "/balance",
        "balance_value_path": "data.remaining_balance",
    }
