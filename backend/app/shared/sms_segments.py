"""SMS encoding detection and segment counting (GSM 03.38 vs UCS-2).

Mirrored in ``frontend/src/lib/sms-segments.ts``; both are tested against
``tests/fixtures/sms_segments.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

GSM7_BASIC = (
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM7_EXTENSION = "^{}\\[~]|€\f"

_BASIC = frozenset(GSM7_BASIC)
_EXT = frozenset(GSM7_EXTENSION)

Encoding = Literal["GSM7", "UCS2"]


@dataclass(frozen=True)
class SegmentInfo:
    encoding: Encoding
    length: int  # in encoding units (septets for GSM7, UTF-16 code units for UCS2)
    segments: int
    per_segment: int
    remaining: int  # characters left in the current segment
    non_gsm_chars: tuple[str, ...] = ()


def detect_encoding(text: str) -> Encoding:
    return "GSM7" if all(c in _BASIC or c in _EXT for c in text) else "UCS2"


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def analyze(text: str) -> SegmentInfo:
    encoding = detect_encoding(text)
    if encoding == "GSM7":
        length = sum(2 if c in _EXT else 1 for c in text)
        single, multi = 160, 153
        non_gsm: tuple[str, ...] = ()
    else:
        length = _utf16_len(text)
        single, multi = 70, 67
        seen: dict[str, None] = {}
        for c in text:
            if c not in _BASIC and c not in _EXT:
                seen.setdefault(c, None)
        non_gsm = tuple(seen)[:20]

    if length == 0:
        segments = 0
        per_segment = single
    elif length <= single:
        segments = 1
        per_segment = single
    else:
        per_segment = multi
        segments = -(-length // multi)
    capacity = max(segments, 1) * per_segment
    return SegmentInfo(
        encoding=encoding,
        length=length,
        segments=segments,
        per_segment=per_segment,
        remaining=capacity - length,
        non_gsm_chars=non_gsm,
    )


def count_segments(text: str) -> int:
    return analyze(text).segments
