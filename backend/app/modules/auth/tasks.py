from __future__ import annotations

from app.shared.email import send_email
from app.workers.registry import task


@task("email.send", queue="default")
async def send_email_task(to: str, subject: str, text: str, html: str | None = None) -> None:
    await send_email(to, subject, text, html)
