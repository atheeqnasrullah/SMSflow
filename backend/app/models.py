"""Import every ORM model so SQLAlchemy metadata (and Alembic) sees all tables."""

from app.core.db import Base
from app.modules.api_keys.models import ApiKey, ApiRequestLog
from app.modules.audit.models import AuditLog
from app.modules.auth.models import RefreshToken, User, UserToken
from app.modules.campaigns.models import Campaign
from app.modules.contacts.models import Contact, ContactGroup, ContactGroupMember, ImportJob, Suppression
from app.modules.messaging.models import IdempotencyRecord, Message, MessageEvent, OtpRequest
from app.modules.payments.models import CreditPackage, Invoice, Payment
from app.modules.providers.models import Provider
from app.modules.sender_ids.models import SenderId
from app.modules.templates.models import Template
from app.modules.tenants.models import Invitation, Membership, SupportTicket, Tenant
from app.modules.wallet.models import LedgerEntry, PricingRule, Wallet
from app.modules.webhooks.models import WebhookDelivery, WebhookEndpoint

__all__ = [
    "Base",
    "ApiKey",
    "ApiRequestLog",
    "AuditLog",
    "Campaign",
    "Contact",
    "ContactGroup",
    "ContactGroupMember",
    "CreditPackage",
    "IdempotencyRecord",
    "ImportJob",
    "Invitation",
    "Invoice",
    "LedgerEntry",
    "Membership",
    "Message",
    "MessageEvent",
    "OtpRequest",
    "Payment",
    "PricingRule",
    "Provider",
    "RefreshToken",
    "SenderId",
    "SupportTicket",
    "Suppression",
    "Template",
    "Tenant",
    "User",
    "UserToken",
    "Wallet",
    "WebhookDelivery",
    "WebhookEndpoint",
]
