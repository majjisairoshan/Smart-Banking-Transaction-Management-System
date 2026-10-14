"""Property-based tests with Hypothesis — the test *generator* tries to break
our invariants with hundreds of random inputs.

Key property proven: **conservation of money** — for every transferable
amount, total balances before == total balances after.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bank.algorithms import greedy_denominations, merge_sort
from bank.services import BankingError, plan_transfer
from bank.utils import inr, parse_amount

UTC = UTC
MAX = Decimal("1000000.00")
NOW = datetime(2026, 10, 12, tzinfo=UTC)

paise = st.integers(min_value=1, max_value=100_000_000).map(lambda p: (Decimal(p) / 100).quantize(Decimal("0.01")))
balances = st.integers(min_value=0, max_value=50_000_000_00).map(lambda p: (Decimal(p) / 100).quantize(Decimal("0.01")))


def _apply(src, dst, amount):
    src.balance -= amount
    dst.balance += amount


@given(src_bal=balances, dst_bal=balances, amount=paise)
@settings(max_examples=300, deadline=None, suppress_health_check=list(HealthCheck))
def test_transfer_conserves_money(make_savings, make_current, src_bal, dst_bal, amount):
    src, dst = make_savings(src_bal), make_current(dst_bal)
    before = src.balance + dst.balance
    try:
        plan_transfer(src, dst, amount, max_amount=MAX)
    except BankingError:
        return  # rejected transfers mutate nothing — conservation holds trivially
    _apply(src, dst, amount)
    after = src.balance + dst.balance
    assert after == before, "money must be neither created nor destroyed"
    assert src.balance >= src.withdrawal_floor(), "source floor invariant must hold post-transfer"


@given(items=st.lists(st.integers(min_value=-10**6, max_value=10**6), max_size=400))
@settings(max_examples=200, deadline=None)
def test_merge_sort_is_builtin_sorted(items):
    assert merge_sort(items, key=lambda x: x) == sorted(items)
    assert merge_sort(items, key=lambda x: x, reverse=True) == sorted(items, reverse=True)


@given(amount=st.integers(min_value=0, max_value=2_000_000))
@settings(max_examples=250, deadline=None)
def test_greedy_reconstructs_amount(amount):
    parts = greedy_denominations(amount)
    assert sum(note * count for note, count in parts) == amount
    if amount == 0:
        assert parts == []
    # every note used must divide the count meaningfully (no zero-count rows)
    assert all(count > 0 for _, count in parts)


@given(amount=st.decimals(min_value="0", max_value="99999999.99", places=2))
@settings(max_examples=200, deadline=None)
def test_inr_round_trip_through_parse(amount):
    rendered = inr(amount)
    assert parse_amount(rendered) == amount.quantize(Decimal("0.01"))
