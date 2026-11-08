"""Money helpers – amounts are Decimal LKR with 4 decimal places, never floats."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Numeric

MoneyType = Numeric(14, 4)
FOUR = Decimal("0.0001")
TWO = Decimal("0.01")


def money(value: Decimal | int | str | float) -> Decimal:
    if isinstance(value, float):
        value = str(value)
    return Decimal(value).quantize(FOUR, rounding=ROUND_HALF_UP)


def money2(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


ZERO = money(0)
