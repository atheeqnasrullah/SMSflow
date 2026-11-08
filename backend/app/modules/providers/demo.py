"""Demo SMS Gateway (Module 7) – a fully in-process provider for dev, tests and demo tenants.

* Accepts messages with ``provider_message_id = "demo-<uuid>"``.
* Emits delivery reports through the *same* ``process_dlr`` path as real providers, after a random
  2–30 s delay, so the rest of the engine cannot tell the difference.
* Magic numbers for failure injection:
  ``+94770000001`` always fails · ``+94770000002`` times out (retryable) · ``+94770000003`` stays pending.
"""

from __future__ import annotations

import random
import uuid
from typing import Any

from app.core.config import settings
from app.modules.providers.base import (
    DeliveryReport,
    DlrRequest,
    OutboundSms,
    ProviderBalance,
    SendResult,
)

ALWAYS_FAIL = "+94770000001"
TIMEOUT = "+94770000002"
STAYS_PENDING = "+94770000003"


class DemoProvider:
    code = "demo"

    def __init__(self, config: dict[str, Any] | None = None, *, seed: int | None = None) -> None:
        cfg = config or {}
        self.delivered_rate = float(cfg.get("delivered_rate", settings.demo_delivered_rate))
        self.failed_rate = float(cfg.get("failed_rate", settings.demo_failed_rate))
        self.transient_error_rate = float(cfg.get("transient_error_rate", settings.demo_transient_error_rate))
        seed = seed if seed is not None else cfg.get("seed", settings.demo_seed)
        self._rng = random.Random(seed)

    async def send(self, msg: OutboundSms) -> SendResult:
        if msg.to == ALWAYS_FAIL:
            return SendResult("permanent_error", error_code="DEMO_REJECTED", error_message="Demo: number always fails")
        if msg.to == TIMEOUT:
            return SendResult("retryable_error", error_code="DEMO_TIMEOUT", error_message="Demo: simulated timeout")
        if self.transient_error_rate and self._rng.random() < self.transient_error_rate:
            return SendResult("retryable_error", error_code="DEMO_TRANSIENT", error_message="Demo: transient error")
        return SendResult("accepted", provider_message_id=f"demo-{uuid.uuid4()}", raw={"demo": True})

    async def send_batch(self, msgs: list[OutboundSms]) -> list[SendResult]:
        return [await self.send(m) for m in msgs]

    async def get_status(self, provider_message_id: str) -> DeliveryReport | None:
        return None

    async def get_balance(self) -> ProviderBalance:
        return ProviderBalance(amount=None, currency=None, raw={"demo": True})

    def parse_dlr(self, request: DlrRequest) -> list[DeliveryReport]:
        data = request.json or {}
        return [DeliveryReport(provider_message_id=data["id"], status=data["status"], raw=data)]

    def verify_callback(self, request: DlrRequest) -> bool:
        return False  # demo DLRs never arrive over HTTP

    # --- simulation ---------------------------------------------------------------------
    def simulate_outcome(self, to: str) -> tuple[str | None, int]:
        """Return (final_status or None for 'no DLR', delay_seconds)."""
        delay = self._rng.randint(settings.demo_dlr_min_delay, settings.demo_dlr_max_delay)
        if to == STAYS_PENDING:
            return None, delay
        r = self._rng.random()
        if r < self.delivered_rate:
            return "delivered", delay
        if r < self.delivered_rate + self.failed_rate:
            return "undelivered", delay
        return None, delay
