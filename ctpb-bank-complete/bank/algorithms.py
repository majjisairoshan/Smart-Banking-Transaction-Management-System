"""Hand-rolled algorithms used across the app (rubric §1).

Each function documents its asymptotic cost.  These are deliberately
implemented from scratch — not because Python's built-ins are slow, but to
demonstrate algorithmic patterns (divide & conquer, binary search, greedy,
sliding window) on real banking data.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol, TypeVar

T = TypeVar("T")


class _Comparable(Protocol):
    """Anything orderable via '<' — the contract our sort/search keys need."""

    def __lt__(self, other: Any, /) -> bool: ...


K = TypeVar("K", bound=_Comparable)


# ---------------------------------------------------------------------------
# Divide and conquer: merge sort (stable) — used to re-sort transaction pages
# ---------------------------------------------------------------------------
def merge_sort(items: Iterable[T], *, key: Callable[[T], K], reverse: bool = False) -> list[T]:
    """Stable merge sort.

    Time Θ(n log n) worst-case, space Θ(n) — unlike quicksort's Θ(n²) worst
    case it is safe for adversarial input, and stability keeps equal keys in
    FIFO order (important for same-timestamp transactions).
    """
    data = list(items)
    if len(data) <= 1:
        return data
    return _split(data, key, reverse)


def _split(seq: list[T], key: Callable[[T], K], reverse: bool) -> list[T]:
    if len(seq) <= 1:
        return seq
    mid = len(seq) // 2
    left = _split(seq[:mid], key, reverse)
    right = _split(seq[mid:], key, reverse)
    return _merge(left, right, key, reverse)


def _merge(left: list[T], right: list[T], key: Callable[[T], K], reverse: bool) -> list[T]:
    out: list[T] = []
    i = j = 0
    while i < len(left) and j < len(right):
        # Expressed with '<' only: taking left when NOT(left > right) <=> left <= right;
        # on ties we always take from the left run first → the sort stays stable.
        take_left = not (key(right[j]) < key(left[i])) if not reverse else not (key(left[i]) < key(right[j]))
        if take_left:
            out.append(left[i])
            i += 1
        else:
            out.append(right[j])
            j += 1
    out.extend(left[i:])
    out.extend(right[j:])
    return out


# ---------------------------------------------------------------------------
# Binary search — locate a transaction by id within an id-sorted page
# ---------------------------------------------------------------------------
def binary_search(sorted_items: Sequence[T], target: K, *, key: Callable[[T], K]) -> int:
    """Classic binary search. Time O(log n), space O(1). Returns index or -1."""
    lo, hi = 0, len(sorted_items) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        value = key(sorted_items[mid])
        if value == target:
            return mid
        if value < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1


# ---------------------------------------------------------------------------
# Greedy: INR cash denomination breakdown (ATM note counter widget)
# ---------------------------------------------------------------------------
INR_DENOMINATIONS: tuple[int, ...] = (2000, 500, 200, 100, 50, 20, 10, 5, 2, 1)


def greedy_denominations(amount: int) -> list[tuple[int, int]]:
    """Break ₹`amount` into the fewest notes/coins.

    Greedy choice: always take the largest note ≤ the remainder.
    Time O(k) with k = number of denominations (here 10, i.e. effectively O(1)).
    Greedy is *optimal* here because INR is a canonical coin system —
    for arbitrary denominations dynamic programming would be required.
    """
    if amount < 0:
        raise ValueError("amount must be non-negative")
    breakdown: list[tuple[int, int]] = []
    remainder = amount
    for note in INR_DENOMINATIONS:
        count, remainder = divmod(remainder, note)
        if count:
            breakdown.append((note, count))
    return breakdown


# ---------------------------------------------------------------------------
# Sliding window + rule engine: transfer risk scoring (pure function)
# ---------------------------------------------------------------------------
def sliding_window_count(timestamps_desc: Iterable[datetime], now: datetime, window: timedelta) -> int:
    """Count events inside ``[now - window, now]``.

    Accepts newest-first timestamps and stops at the first event older than
    the window — O(k) where k is the answer, instead of O(n) for a full scan.
    """
    cutoff = now - window
    hits = 0
    for ts in timestamps_desc:
        if ts < cutoff:
            break
        hits += 1
    return hits


def assess_transfer_risk(
    *,
    amount: Decimal,
    recent_outbound_desc: Iterable[datetime],
    now: datetime,
    window: timedelta,
    velocity_limit: int,
    amount_threshold: Decimal,
) -> tuple[str, ...]:
    """Pure rule engine — returns human-readable reasons (empty = clean).

    * amount at/above the reporting threshold, or
    * more than ``velocity_limit`` outbound transfers inside ``window``.
    """
    reasons: list[str] = []
    if amount >= amount_threshold:
        reasons.append(f"amount ≥ ₹{amount_threshold:,.0f}")
    hits = sliding_window_count(recent_outbound_desc, now, window)
    if hits >= velocity_limit:
        reasons.append(f"{hits + 1} transfers within {int(window.total_seconds())}s")
    return tuple(reasons)


# ---------------------------------------------------------------------------
# Top-K — 'largest transactions' for the admin console
# ---------------------------------------------------------------------------
def top_k(items: Iterable[T], k: int, *, key: Callable[[T], K], reverse: bool = True) -> list[T]:
    """O(n log n) via merge sort for clarity (n is small); heapq.nlargest is O(n log k)."""
    return merge_sort(items, key=key, reverse=reverse)[:k]
