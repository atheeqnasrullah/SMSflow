"""Seed reference data and (optionally) a demo workspace.

    python -m app.scripts.seed                 # providers, packages, pricing, platform admin
    python -m app.scripts.seed --demo-tenant   # + demo business with contacts and templates

Admin credentials come from SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD (defaults are for local dev only).
"""

from __future__ import annotations

import argparse
import asyncio
import os
from decimal import Decimal

from sqlalchemy import select

from app.core.config import settings
from app.core.db import system_session
from app.core.security import encrypt_json, hash_password
from app.models import (
    Contact,
    ContactGroup,
    ContactGroupMember,
    CreditPackage,
    PricingRule,
    Provider,
    SenderId,
    Template,
    User,
)

PACKAGES = [
    ("Starter", "Try it out", Decimal("1000"), Decimal("1000"), Decimal("0"), 1),
    ("Business", "For growing businesses", Decimal("5000"), Decimal("5000"), Decimal("250"), 2),
    ("Pro", "High-volume senders", Decimal("20000"), Decimal("20000"), Decimal("2000"), 3),
    ("Enterprise", "Campaigns at scale", Decimal("100000"), Decimal("100000"), Decimal("15000"), 4),
]


async def seed_reference() -> None:
    async with system_session() as s:
        if not await s.scalar(select(Provider.id).where(Provider.code == "demo")):
            s.add(Provider(name="Demo SMS Gateway", type="demo", code="demo", priority=1000,
                           config_encrypted=encrypt_json({}), cost_per_segment=Decimal(0), max_tps=1000))
        if not await s.scalar(select(CreditPackage.id)):
            for name, desc, price, credits, bonus, order in PACKAGES:
                s.add(CreditPackage(name=name, description=desc, price_lkr=price, credits=credits,
                                    bonus_credits=bonus, sort_order=order))
        if not await s.scalar(select(PricingRule.id).where(PricingRule.tenant_id.is_(None))):
            s.add(PricingRule(message_category=None, price_per_segment=settings.default_price_per_segment))
            s.add(PricingRule(message_category="otp", price_per_segment=Decimal("0.9500")))
        email = os.environ.get("SEED_ADMIN_EMAIL", "admin@smsflow.lk").lower()
        password = os.environ.get("SEED_ADMIN_PASSWORD", "ChangeMe-Admin-123")
        if not await s.scalar(select(User.id).where(User.email == email)):
            from app.core.db import utcnow

            s.add(User(email=email, password_hash=hash_password(password), full_name="Platform Admin",
                       is_platform_admin=True, email_verified_at=utcnow()))
            print(f"Created platform admin {email}")
        await s.commit()


async def seed_demo_tenant() -> None:
    from app.core.db import utcnow
    from app.modules.auth.service import create_tenant_with_owner

    email = "owner@lankamart.lk"
    async with system_session() as s:
        if await s.scalar(select(User.id).where(User.email == email)):
            print("Demo tenant already exists")
            return
        user = User(email=email, password_hash=hash_password("DemoOwner-123"), full_name="Nimal Perera",
                    email_verified_at=utcnow())
        s.add(user)
        await s.flush()
        tenant = await create_tenant_with_owner(s, user=user, name="Lanka Mart", business_type="Retail")
        group = ContactGroup(tenant_id=tenant.id, name="Loyalty customers", description="Seeded demo group")
        s.add(group)
        await s.flush()
        names = [("Kasun", "Silva"), ("Ayesha", "Fernando"), ("Tharindu", "Jayasinghe"), ("Dilini", "Wickramasinghe"),
                 ("Mohamed", "Rizwan"), ("Priya", "Rajendran"), ("Chamara", "Bandara"), ("Nadeesha", "Kumari")]
        for i, (first, last) in enumerate(names):
            c = Contact(tenant_id=tenant.id, phone_e164=f"+9477{1000000 + i * 1111:07d}", first_name=first, last_name=last,
                        consent_status="granted", consent_source="seed", consent_at=utcnow(),
                        attributes={"city": ["Colombo", "Kandy", "Galle", "Jaffna"][i % 4]})
            s.add(c)
            await s.flush()
            s.add(ContactGroupMember(tenant_id=tenant.id, group_id=group.id, contact_id=c.id))
        s.add(Template(tenant_id=tenant.id, name="Order confirmation", category="transactional",
                       body="Hi {{first_name}}, your order has been confirmed. Thank you for shopping at Lanka Mart!",
                       variables=["first_name"]))
        s.add(Template(tenant_id=tenant.id, name="Weekend sale", category="promotional",
                       body="{{first_name}}, 20% off everything this weekend at Lanka Mart {{city}}! Reply STOP to opt out.",
                       variables=["first_name", "city"]))
        s.add(SenderId(tenant_id=tenant.id, value="LANKAMART", status="pending", purpose="Order updates and promotions"))
        await s.commit()
        print(f"Created demo workspace 'Lanka Mart' – login {email} / DemoOwner-123")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo-tenant", action="store_true")
    args = parser.parse_args()
    await seed_reference()
    if args.demo_tenant:
        await seed_demo_tenant()


if __name__ == "__main__":
    asyncio.run(main())
