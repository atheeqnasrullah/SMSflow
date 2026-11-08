"""Application settings, loaded from environment variables (and `.env` in local dev)."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- General -----------------------------------------------------------------
    env: Literal["local", "test", "staging", "production"] = "local"
    app_name: str = "SMSFlow"
    api_prefix: str = "/api/v1"
    frontend_url: str = "http://localhost:3000"
    api_public_url: str = "http://localhost:8000"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])
    log_level: str = "INFO"
    log_json: bool = False
    sentry_dsn: str | None = None

    # --- Database ----------------------------------------------------------------
    # Application role: NO BYPASSRLS. Every tenant request runs under RLS.
    database_url: str = "sqlite+aiosqlite:///./smsflow.db"
    # System/admin role (BYPASSRLS) used for platform-admin endpoints and cross-tenant jobs
    # (DLR lookup, due-campaign dispatch, auth lookups). Falls back to database_url.
    admin_database_url: str | None = None
    db_echo: bool = False
    db_null_pool: bool = False  # set in Celery workers (one event loop per task process)

    # --- Redis / tasks -------------------------------------------------------------
    redis_url: str = "memory://"
    celery_broker_url: str | None = None
    # "celery" = enqueue to Redis for worker processes; "inline" = run in-process (dev/tests)
    task_mode: Literal["celery", "inline"] = "inline"

    # --- Security --------------------------------------------------------------------
    jwt_secret: str = "change-me-local-dev-secret-change-me-local-dev-secret"
    jwt_algorithm: Literal["HS256", "RS256", "EdDSA"] = "HS256"
    jwt_private_key: str | None = None  # PEM, for RS256/EdDSA
    jwt_public_key: str | None = None
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    # base64-encoded 32 byte key for AES-GCM (provider credentials, webhook secrets)
    encryption_key: str = "bG9jYWwtZGV2LWtleS1kby1ub3QtdXNlLWluLXByb2Q="
    otp_hash_secret: str = "change-me-otp-secret"
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    refresh_cookie_name: str = "sf_refresh"

    # --- Messaging ---------------------------------------------------------------------
    default_country: str = "LK"
    default_price_per_segment: Decimal = Decimal("0.8500")
    currency: str = "LKR"
    demo_signup_credits: int = 500  # demo segments granted at registration
    demo_default_sender: str = "SMSFlow"
    demo_delivered_rate: float = 0.90
    demo_failed_rate: float = 0.06
    demo_transient_error_rate: float = 0.0
    demo_dlr_min_delay: int = 2
    demo_dlr_max_delay: int = 30
    demo_seed: int | None = None
    max_send_attempts: int = 5
    campaign_batch_size: int = 1000
    quiet_hours_enabled: bool = True
    quiet_hours_start: int = 21  # Asia/Colombo
    quiet_hours_end: int = 8
    dlr_unknown_after_hours: int = 48
    refund_undelivered: bool = False
    new_tenant_daily_cap: int = 1000  # live messages / day for tenants younger than 7 days

    # --- OTP -------------------------------------------------------------------------
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_length: int = 6
    otp_max_per_number_per_10min: int = 3

    # --- API ---------------------------------------------------------------------------
    rate_limit_per_second: int = 10
    bulk_max_messages: int = 1000
    idempotency_ttl_hours: int = 24

    # --- Webhooks ----------------------------------------------------------------------
    webhook_allow_private_targets: bool = False
    webhook_timeout_seconds: float = 10.0
    webhook_disable_after_failures: int = 15

    # --- Payments (PayHere) ---------------------------------------------------------------
    payhere_merchant_id: str | None = None
    payhere_merchant_secret: str | None = None
    payhere_sandbox: bool = True
    allow_payment_simulation: bool = True  # dev-only "simulate successful payment"

    # --- Email ----------------------------------------------------------------------------
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    email_from: str = "SMSFlow <no-reply@smsflow.lk>"

    # --- Storage ---------------------------------------------------------------------------
    storage_dir: str = "./storage"
    max_import_bytes: int = 5 * 1024 * 1024

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip().startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def broker_url(self) -> str:
        if self.celery_broker_url:
            return self.celery_broker_url
        return self.redis_url if self.redis_url.startswith("redis") else "memory://"

    @property
    def payhere_checkout_url(self) -> str:
        return (
            "https://sandbox.payhere.lk/pay/checkout"
            if self.payhere_sandbox
            else "https://www.payhere.lk/pay/checkout"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
