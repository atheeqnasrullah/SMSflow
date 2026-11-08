"""Very small, safe template language: ``{{variable}}`` placeholders, no code execution."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class MissingVariable(KeyError):
    pass


def extract_variables(body: str) -> list[str]:
    seen: dict[str, None] = {}
    for m in VAR_RE.finditer(body):
        seen.setdefault(m.group(1), None)
    return list(seen)


def render(body: str, values: Mapping[str, Any], *, fallback: str | None = None) -> str:
    """Render placeholders. Missing values raise :class:`MissingVariable` unless ``fallback``."""

    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        val = values.get(key)
        if val is None or val == "":
            if fallback is None:
                raise MissingVariable(key)
            return fallback
        return str(val)

    return VAR_RE.sub(_sub, body)


def contact_variables(contact: Any) -> dict[str, Any]:
    """Flatten a contact into template variables."""
    values: dict[str, Any] = dict(contact.attributes or {})
    values.update(
        first_name=contact.first_name,
        last_name=contact.last_name,
        name=" ".join(p for p in (contact.first_name, contact.last_name) if p) or None,
        phone=contact.phone_e164,
        email=contact.email,
    )
    return values
