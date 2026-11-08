"""Provider adapter interface. Every SMS provider (demo or real) implements :class:`SmsProvider`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

SendOutcome = Literal["accepted", "retryable_error", "permanent_error"]
DlrStatus = Literal["delivered", "undelivered", "accepted", "unknown"]


@dataclass(frozen=True)
class OutboundSms:
    message_id: str
    to: str  # E.164
    sender: str
    body: str
    encoding: str
    segments: int
    tenant_id: str
    category: str = "transactional"


@dataclass
class SendResult:
    outcome: SendOutcome
    provider_message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeliveryReport:
    provider_message_id: str
    status: DlrStatus
    error_code: str | None = None
    occurred_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderBalance:
    amount: Decimal | None
    currency: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class DlrRequest:
    headers: dict[str, str]
    query: dict[str, str]
    body: bytes
    form: dict[str, str]
    json: Any
    client_ip: str | None


class SmsProvider(Protocol):
    code: str

    async def send(self, msg: OutboundSms) -> SendResult: ...

    async def send_batch(self, msgs: list[OutboundSms]) -> list[SendResult]: ...

    async def get_status(self, provider_message_id: str) -> DeliveryReport | None: ...

    async def get_balance(self) -> ProviderBalance: ...

    def parse_dlr(self, request: DlrRequest) -> list[DeliveryReport]: ...

    def verify_callback(self, request: DlrRequest) -> bool: ...


class BaseHttpProvider:
    """Shared helpers for HTTP based adapters."""

    code = "base"
    timeout = 15.0

    def __init__(self, config: dict[str, Any], *, provider_code: str | None = None) -> None:
        self.config = config
        if provider_code:
            self.code = provider_code

    async def send_batch(self, msgs: list[OutboundSms]) -> list[SendResult]:
        return [await self.send(m) for m in msgs]  # type: ignore[attr-defined]

    async def get_status(self, provider_message_id: str) -> DeliveryReport | None:
        return None

    async def get_balance(self) -> ProviderBalance:
        return ProviderBalance(amount=None)

    def verify_callback(self, request: DlrRequest) -> bool:
        """Default: shared-secret token in query string (?token=...) and optional IP allow-list."""
        import hmac

        expected = self.config.get("callback_token")
        allowed_ips = self.config.get("callback_ips") or []
        if allowed_ips and request.client_ip not in allowed_ips:
            return False
        if not expected:
            return False
        got = request.query.get("token") or request.headers.get("x-callback-token") or ""
        return hmac.compare_digest(str(expected), got)

    @staticmethod
    def classify_http(status_code: int) -> SendOutcome:
        if status_code in (408, 425, 429) or status_code >= 500:
            return "retryable_error"
        return "permanent_error"
