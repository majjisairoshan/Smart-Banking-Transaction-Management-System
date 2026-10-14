"""Unit tests for the pure transfer validator ``plan_transfer``."""
from __future__ import annotations

from decimal import Decimal

import pytest

from bank.models import AccountStatus
from bank.services import (
    FrozenAccountError,
    InsufficientFundsError,
    InvalidAmountError,
    SameAccountError,
    plan_transfer,
)

MAX = Decimal("1000000.00")


def test_happy_path(make_savings, make_current):
    plan_transfer(make_savings("5000"), make_current("100"), Decimal("1500.50"), max_amount=MAX)


@pytest.mark.parametrize("bad", ["0", "-1", "-0.01"])
def test_non_positive_rejected(make_savings, make_current, bad):
    with pytest.raises(InvalidAmountError):
        plan_transfer(make_savings(), make_current(), Decimal(bad), max_amount=MAX)


def test_three_decimal_places_rejected(make_savings, make_current):
    with pytest.raises(InvalidAmountError):
        plan_transfer(make_savings(), make_current(), Decimal("1.001"), max_amount=MAX)


def test_above_single_transfer_cap(make_savings, make_current):
    with pytest.raises(InvalidAmountError):
        plan_transfer(make_savings("9999999"), make_current(), Decimal("1000000.01"), max_amount=MAX)


def test_same_account_rejected(make_savings, make_current):
    other = make_current(number="5000000001")  # same number, different object
    with pytest.raises(SameAccountError):
        plan_transfer(make_savings(), other, Decimal("10"), max_amount=MAX)


def test_frozen_source(make_savings, make_current):
    with pytest.raises(FrozenAccountError):
        plan_transfer(make_savings(status=AccountStatus.FROZEN), make_current(), Decimal("10"), max_amount=MAX)


def test_frozen_destination(make_savings, make_current):
    with pytest.raises(FrozenAccountError):
        plan_transfer(make_savings(), make_current(status=AccountStatus.FROZEN), Decimal("10"), max_amount=MAX)


def test_savings_insufficient_reports_headroom(make_savings, make_current):
    with pytest.raises(InsufficientFundsError) as exc:
        plan_transfer(make_savings("3000"), make_current(), Decimal("2500"), max_amount=MAX)
    assert exc.value.account.balance - exc.value.account.withdrawal_floor() == Decimal("2000")


def test_current_overdraft_exceeded(make_savings, make_current):
    with pytest.raises(InsufficientFundsError):
        plan_transfer(make_current("1000"), make_savings(), Decimal("51000.01"), max_amount=MAX)


def test_current_overdraft_allowed_within_limit(make_savings, make_current):
    plan_transfer(make_current("1000"), make_savings(), Decimal("50999.99"), max_amount=MAX)
