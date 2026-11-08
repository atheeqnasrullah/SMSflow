"""Workspace profile, team management, invitations and support tickets."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import system_session, utcnow
from app.core.deps import Principal, TenantSession, client_ip, require
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.permissions import P, Role
from app.core.security import new_opaque_token, sha256_hex
from app.modules.audit.service import record_principal
from app.modules.auth.models import User
from app.modules.tenants.models import Invitation, Membership, SupportTicket, Tenant
from app.workers.dispatch import defer

router = APIRouter(prefix="/workspace", tags=["workspace"])


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    business_type: str | None
    status: str
    mode: str
    country: str
    timezone: str
    contact_email: str | None
    contact_phone: str | None
    address: str | None
    live_requested_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    business_type: str | None = None
    contact_email: EmailStr | None = None
    contact_phone: str | None = None
    address: str | None = None


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: str
    status: str
    joined_at: datetime


class InviteIn(BaseModel):
    email: EmailStr
    role: Role


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RoleUpdate(BaseModel):
    role: Role


class TicketIn(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=3, max_length=5000)
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")


class TicketOut(BaseModel):
    id: uuid.UUID
    subject: str
    body: str
    status: str
    priority: str
    admin_notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


async def _tenant(session: TenantSession, principal: Principal) -> Tenant:
    tenant = await session.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise NotFound("Workspace not found")
    return tenant


@router.get("", response_model=WorkspaceOut)
async def get_workspace(session: TenantSession, principal: Principal = Depends(require(P.REPORTS_READ))) -> Tenant:
    return await _tenant(session, principal)


@router.patch("", response_model=WorkspaceOut)
async def update_workspace(
    data: WorkspaceUpdate, request: Request, session: TenantSession,
    principal: Principal = Depends(require(P.WORKSPACE_UPDATE)),
) -> Tenant:
    tenant = await _tenant(session, principal)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(tenant, k, v)
    record_principal(session, principal, "workspace.updated", target_type="tenant", target_id=tenant.id,
                     ip=client_ip(request))
    await session.commit()
    return tenant


@router.post("/request-live", response_model=WorkspaceOut)
async def request_live(session: TenantSession, principal: Principal = Depends(require(P.WORKSPACE_UPDATE))) -> Tenant:
    """Ask SMSFlow staff to move the workspace from demo to live mode (requires review)."""
    tenant = await _tenant(session, principal)
    if tenant.mode == "live":
        raise Conflict("Workspace is already live")
    tenant.live_requested_at = utcnow()
    session.add(SupportTicket(
        tenant_id=tenant.id, subject="Go-live request", priority="high", created_by=principal.user_id,
        body=f"Workspace '{tenant.name}' requests live mode.",
    ))
    await session.commit()
    return tenant


@router.get("/members", response_model=list[MemberOut])
async def list_members(principal: Principal = Depends(require(P.REPORTS_READ))) -> list[MemberOut]:
    async with system_session() as s:
        rows = (
            await s.execute(
                select(Membership, User)
                .join(User, User.id == Membership.user_id)
                .where(Membership.tenant_id == principal.tenant_id)
                .order_by(Membership.created_at)
            )
        ).all()
    return [
        MemberOut(user_id=u.id, email=u.email, full_name=u.full_name, role=m.role, status=m.status, joined_at=m.created_at)
        for m, u in rows
    ]


@router.patch("/members/{user_id}", response_model=MemberOut)
async def update_member(
    user_id: uuid.UUID, data: RoleUpdate, request: Request, principal: Principal = Depends(require(P.TEAM_MANAGE))
) -> MemberOut:
    async with system_session() as s:
        m = await s.scalar(select(Membership).where(Membership.tenant_id == principal.tenant_id, Membership.user_id == user_id))
        if m is None:
            raise NotFound("Member not found")
        if m.role == Role.owner.value or data.role == Role.owner:
            if principal.role != Role.owner.value:
                raise Forbidden("Only the owner can transfer ownership")
            if data.role == Role.owner:  # transfer ownership
                me = await s.scalar(select(Membership).where(
                    Membership.tenant_id == principal.tenant_id, Membership.user_id == principal.user_id))
                assert me is not None
                me.role = Role.admin.value
        old = m.role
        m.role = data.role.value
        record_principal(s, principal, "team.role_changed", target_type="user", target_id=user_id,
                         metadata={"from": old, "to": m.role}, ip=client_ip(request))
        await s.commit()
        u = await s.get(User, user_id)
        assert u is not None
        return MemberOut(user_id=u.id, email=u.email, full_name=u.full_name, role=m.role, status=m.status, joined_at=m.created_at)


@router.delete("/members/{user_id}", status_code=204)
async def remove_member(
    user_id: uuid.UUID, request: Request, principal: Principal = Depends(require(P.TEAM_MANAGE))
) -> Response:
    async with system_session() as s:
        m = await s.scalar(select(Membership).where(Membership.tenant_id == principal.tenant_id, Membership.user_id == user_id))
        if m is None:
            raise NotFound("Member not found")
        if m.role == Role.owner.value:
            raise Forbidden("The owner cannot be removed; transfer ownership first")
        await s.delete(m)
        record_principal(s, principal, "team.member_removed", target_type="user", target_id=user_id, ip=client_ip(request))
        await s.commit()
    return Response(status_code=204)


@router.get("/invitations", response_model=list[InvitationOut])
async def list_invitations(principal: Principal = Depends(require(P.TEAM_MANAGE))) -> list[Invitation]:
    async with system_session() as s:
        return list((await s.scalars(
            select(Invitation).where(Invitation.tenant_id == principal.tenant_id).order_by(Invitation.created_at.desc())
        )).all())


@router.post("/invitations", response_model=InvitationOut, status_code=201)
async def invite(data: InviteIn, request: Request, principal: Principal = Depends(require(P.TEAM_MANAGE))) -> Invitation:
    if data.role == Role.owner:
        raise ValidationFailed("Invite as admin, then transfer ownership")
    email = data.email.lower()
    async with system_session() as s:
        already = await s.scalar(
            select(func.count()).select_from(Membership).join(User, User.id == Membership.user_id)
            .where(Membership.tenant_id == principal.tenant_id, User.email == email)
        )
        if already:
            raise Conflict("That user is already a member")
        tenant = await s.get(Tenant, principal.tenant_id)
        raw = new_opaque_token()
        inv = Invitation(
            tenant_id=principal.tenant_id, email=email, role=data.role.value, token_hash=sha256_hex(raw),
            invited_by=principal.user_id, expires_at=utcnow() + timedelta(days=7),
        )
        s.add(inv)
        defer(s, "email.send", to=email, subject=f"You're invited to {tenant.name if tenant else 'SMSFlow'}",
              text=f"You have been invited to join {tenant.name if tenant else 'a workspace'} on SMSFlow as "
                   f"{data.role.value}.\n\nAccept: {settings.frontend_url}/accept-invitation?token={raw}\n")
        record_principal(s, principal, "team.invited", target_type="invitation", metadata={"email": email, "role": data.role.value},
                         ip=client_ip(request))
        await s.commit()
        return inv


@router.delete("/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(invitation_id: uuid.UUID, principal: Principal = Depends(require(P.TEAM_MANAGE))) -> Response:
    async with system_session() as s:
        inv = await s.scalar(select(Invitation).where(Invitation.id == invitation_id, Invitation.tenant_id == principal.tenant_id))
        if inv is None:
            raise NotFound("Invitation not found")
        inv.revoked_at = utcnow()
        await s.commit()
    return Response(status_code=204)


@router.get("/support-tickets", response_model=list[TicketOut])
async def list_tickets(principal: Principal = Depends(require(P.REPORTS_READ))) -> list[SupportTicket]:
    async with system_session() as s:
        return list((await s.scalars(
            select(SupportTicket).where(SupportTicket.tenant_id == principal.tenant_id).order_by(SupportTicket.created_at.desc())
        )).all())


@router.post("/support-tickets", response_model=TicketOut, status_code=201)
async def create_ticket(data: TicketIn, principal: Principal = Depends(require(P.REPORTS_READ))) -> SupportTicket:
    async with system_session() as s:
        t = SupportTicket(tenant_id=principal.tenant_id, subject=data.subject, body=data.body, priority=data.priority,
                          created_by=principal.user_id)
        s.add(t)
        await s.commit()
        return t
