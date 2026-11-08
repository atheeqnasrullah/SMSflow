"""Twilio adapter (international fallback). Config: account_sid, auth_token, messaging_service_sid?"""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any

import httpx

from app.core.config import settings
from app.modules.providers.base import (
    BaseHttpProvider,
    DeliveryReport,
    DlrRequest,
    OutboundSms,
    ProviderBalance,
    SendResult,
)

_STATUS = {
    "delivered": "delivered",
    "undelivered": "undelivered",
    "failed": "undelivered",
    "sent": "accepted",
    "queued": "accepted",
    "accepted": "accepted",
}

# https://www.twilio.com/docs/api/errors – errors that will not succeed on retry
_PERMANENT = {"21211", "21408", "21610", "21612", "21614", "30003", "30005", "30006", "30007"}


class TwilioProvider(BaseHttpProvider):
    code = "twilio"

    @property
    def _base(self) -> str:
        return f"https://api.twilio.com/2010-04-01/Accounts/{self.config['account_sid']}"

    def _auth(self) -> tuple[str, str]:
        return (self.config["account_sid"], self.config["auth_token"])

    async def send(self, msg: OutboundSms) -> SendResult:
        data: dict[str, Any] = {
            "To": msg.to,
            "Body": msg.body,
            "StatusCallback": f"{settings.api_public_url}{settings.api_prefix}/callbacks/dlr/{self.code}",
        }
        if self.config.get("messaging_service_sid"):
            data["MessagingServiceSid"] = self.config["messaging_service_sid"]
        else:
            data["From"] = msg.sender
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self._base}/Messages.json", data=data, auth=self._auth())
        except httpx.TimeoutException:
            return SendResult("retryable_error", error_code="TIMEOUT")
        except httpx.HTTPError as exc:
            return SendResult("retryable_error", error_code="NETWORK", error_message=str(exc))
        body = resp.json() if resp.content else {}
        if resp.status_code in (200, 201):
            return SendResult("accepted", provider_message_id=body.get("sid"), raw=body)
        code = str(body.get("code", resp.status_code))
        outcome = "permanent_error" if code in _PERMANENT else self.classify_http(resp.status_code)
        return SendResult(outcome, error_code=code, error_message=body.get("message"), raw=body)

    async def get_status(self, provider_message_id: str) -> DeliveryReport | None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self._base}/Messages/{provider_message_id}.json", auth=self._auth())
        if resp.status_code != 200:
            return None
        body = resp.json()
        return DeliveryReport(
            provider_message_id=provider_message_id,
            status=_STATUS.get(body.get("status", ""), "unknown"),  # type: ignore[arg-type]
            error_code=str(body["error_code"]) if body.get("error_code") else None,
            raw=body,
        )

    async def get_balance(self) -> ProviderBalance:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self._base}/Balance.json", auth=self._auth())
        body = resp.json() if resp.status_code == 200 else {}
        from decimal import Decimal

        amount = Decimal(body["balance"]) if body.get("balance") else None
        return ProviderBalance(amount=amount, currency=body.get("currency"), raw=body)

    def verify_callback(self, request: DlrRequest) -> bool:
        """Validate X-Twilio-Signature (HMAC-SHA1 of URL + sorted POST params)."""
        signature = request.headers.get("x-twilio-signature", "")
        url = f"{settings.api_public_url}{settings.api_prefix}/callbacks/dlr/{self.code}"
        payload = url + "".join(f"{k}{v}" for k, v in sorted(request.form.items()))
        expected = base64.b64encode(
            hmac.new(self.config["auth_token"].encode(), payload.encode(), hashlib.sha1).digest()
        ).decode()
        return hmac.compare_digest(expected, signature)

    def parse_dlr(self, request: DlrRequest) -> list[DeliveryReport]:
        f = request.form
        sid = f.get("MessageSid") or f.get("SmsSid")
        if not sid:
            return []
        status = _STATUS.get(f.get("MessageStatus", ""), "unknown")
        return [
            DeliveryReport(
                provider_message_id=sid,
                status=status,  # type: ignore[arg-type]
                error_code=f.get("ErrorCode"),
                raw=dict(f),
            )
        ]
