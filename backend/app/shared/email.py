"""Outbound email (SMTP). Without SMTP configured, emails are logged (local dev)."""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

import structlog

from app.core.config import settings

log = structlog.get_logger("smsflow.email")


def _send_sync(to: str, subject: str, text: str, html: str | None) -> None:
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    assert settings.smtp_host
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password or "")
        smtp.send_message(msg)


async def send_email(to: str, subject: str, text: str, html: str | None = None) -> None:
    if not settings.smtp_host:
        log.info("email_not_sent_no_smtp", to=to, subject=subject, body=text)
        return
    await asyncio.to_thread(_send_sync, to, subject, text, html)
