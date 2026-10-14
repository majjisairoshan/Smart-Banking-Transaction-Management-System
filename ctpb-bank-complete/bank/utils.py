"""Small pure helpers: formatting, masking, id generation, amount parsing."""
from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from .models import money_round

IST = ZoneInfo("Asia/Kolkata")

_DIGITS_RE = re.compile(r"\D+")
_AMOUNT_RE = re.compile(r"^-?\d+(\.\d{1,2})?$")


def to_ist(dt: datetime) -> datetime:
    """Render an aware datetime in Asia/Kolkata (the bank's display timezone)."""
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(IST)


def ist(dt: datetime, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    return to_ist(dt).strftime(fmt)


def inr(value: Decimal) -> str:
    """Format money with Indian digit grouping: ₹1,23,456.00."""
    v = money_round(Decimal(str(value)))
    sign = "-" if v < 0 else ""
    int_part, _, frac = f"{abs(v):.2f}".partition(".")
    if len(int_part) > 3:
        last3, rest = int_part[-3:], int_part[:-3]
        groups: list[str] = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        int_part = ",".join([*groups, last3])
    return f"{sign}₹{int_part}.{frac}"


def mask_account(number: str) -> str:
    """Show only the last 4 digits: 5010234821 → ···· 4821."""
    return f"···· {number[-4:]}"


def initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    return "".join(p[0] for p in parts[:2]).upper()


def normalize_account_number(raw: str) -> str:
    """Strip spaces/dashes from a typed/pasted account number."""
    return _DIGITS_RE.sub("", raw or "")


def parse_amount(raw: str) -> Decimal:
    """Strictly parse a user-typed amount ('12,500.50' → Decimal('12500.50'))."""
    cleaned = (raw or "").replace(",", "").replace("₹", "").strip()
    if not _AMOUNT_RE.match(cleaned):
        raise ValueError(f"invalid amount: {raw!r}")
    return money_round(Decimal(cleaned))


def new_account_number() -> str:
    """10-digit account number in the 50-series, cryptographically random."""
    return "50" + "".join(secrets.choice("0123456789") for _ in range(8))


def new_txn_ref() -> str:
    return "TXN" + uuid.uuid4().hex[:12].upper()


def sparkline_points(values: list[float], width: int = 132, height: int = 40, pad: int = 2) -> str:
    """Normalise a series into an SVG polyline points string."""
    if not values:
        return ""
    if len(values) == 1:
        values = values * 2
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    step = (width - 2 * pad) / (len(values) - 1)
    pts = [
        f"{pad + i * step:.1f},{height - pad - ((v - lo) / span) * (height - 2 * pad):.1f}"
        for i, v in enumerate(values)
    ]
    return " ".join(pts)
