"""RBAC: permissions, role → permission mapping and API-key scope → permission mapping."""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    owner = "owner"
    admin = "admin"
    manager = "manager"
    operator = "operator"
    viewer = "viewer"


class P:
    BILLING_MANAGE = "billing:manage"
    BILLING_READ = "billing:read"
    TEAM_MANAGE = "team:manage"
    WORKSPACE_DELETE = "workspace:delete"
    WORKSPACE_UPDATE = "workspace:update"
    DEVELOPERS_MANAGE = "developers:manage"
    SENDER_IDS_REQUEST = "sender_ids:request"
    CONTACTS_READ = "contacts:read"
    CONTACTS_WRITE = "contacts:write"
    CAMPAIGNS_READ = "campaigns:read"
    CAMPAIGNS_WRITE = "campaigns:write"
    CAMPAIGNS_LAUNCH = "campaigns:launch"
    TEMPLATES_READ = "templates:read"
    TEMPLATES_WRITE = "templates:write"
    MESSAGES_SEND = "messages:send"
    MESSAGES_READ = "messages:read"
    REPORTS_READ = "reports:read"
    OTP = "otp"


_VIEWER = {
    P.REPORTS_READ,
    P.CAMPAIGNS_READ,
    P.MESSAGES_READ,
    P.TEMPLATES_READ,
    P.BILLING_READ,
}
_OPERATOR = _VIEWER | {P.MESSAGES_SEND, P.CAMPAIGNS_LAUNCH, P.CONTACTS_READ, P.OTP}
_MANAGER = _OPERATOR | {
    P.SENDER_IDS_REQUEST,
    P.CONTACTS_WRITE,
    P.CAMPAIGNS_WRITE,
    P.TEMPLATES_WRITE,
}
_ADMIN = _MANAGER | {P.BILLING_MANAGE, P.TEAM_MANAGE, P.DEVELOPERS_MANAGE, P.WORKSPACE_UPDATE}
_OWNER = _ADMIN | {P.WORKSPACE_DELETE}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    Role.owner.value: frozenset(_OWNER),
    Role.admin.value: frozenset(_ADMIN),
    Role.manager.value: frozenset(_MANAGER),
    Role.operator.value: frozenset(_OPERATOR),
    Role.viewer.value: frozenset(_VIEWER),
}

API_SCOPES: dict[str, frozenset[str]] = {
    "sms:send": frozenset({P.MESSAGES_SEND}),
    "sms:read": frozenset({P.MESSAGES_READ}),
    "otp": frozenset({P.OTP}),
    "contacts:read": frozenset({P.CONTACTS_READ}),
    "contacts:write": frozenset({P.CONTACTS_READ, P.CONTACTS_WRITE}),
    "balance:read": frozenset({P.BILLING_READ}),
    "templates:read": frozenset({P.TEMPLATES_READ}),
    "campaigns:read": frozenset({P.CAMPAIGNS_READ}),
}

ALL_SCOPES = tuple(API_SCOPES)


def permissions_for_role(role: str | None) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role or "", frozenset())


def permissions_for_scopes(scopes: list[str]) -> frozenset[str]:
    out: set[str] = set()
    for s in scopes:
        out |= API_SCOPES.get(s, frozenset())
    return frozenset(out)
