"""Unit tests for the domain model (account invariants, interest, factory)."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from bank.models import (
    AccountStatus,
    CurrentAccount,
    SavingsAccount,
    account_from_row,
    money_round,
)

UTC = UTC


class TestSavingsAccount:
    def test_debit_leaving_exactly_min_balance_is_allowed(self, make_savings):
        acc = make_savings("5000.00")
        # 5000 - 4000 = 1000 == MIN_BALANCE → allowed (floor is inclusive)
        assert acc.can_debit(Decimal("4000.00"))

    def test_debit_below_min_balance_rejected(self, make_savings):
        acc = make_savings("5000.00")
        assert not acc.can_debit(Decimal("4000.01"))

    def test_frozen_account_cannot_debit(self, make_savings):
        acc = make_savings("90000.00", status=AccountStatus.FROZEN)
        assert not acc.can_debit(Decimal("1.00"))
        assert not acc.can_credit()

    def test_monthly_interest(self, make_savings):
        # 120000 * 4% / 12 = 400.00
        assert make_savings("120000.00").monthly_interest() == Decimal("400.00")

    def test_monthly_interest_rounds_half_up(self, make_savings):
        # 1 * 0.04 / 12 = 0.00333… → 0.00 after rounding to paise
        assert make_savings("1.00").monthly_interest() == Decimal("0.00")


class TestCurrentAccount:
    def test_overdraft_boundary_is_inclusive(self, make_current):
        acc = make_current("20000.00")
        assert acc.can_debit(Decimal("70000.00"))      # lands exactly on -50,000
        assert not acc.can_debit(Decimal("70000.01"))  # one paise beyond

    def test_no_interest_on_current(self, make_current):
        assert make_current("500000.00").monthly_interest() == Decimal("0.00")


class TestFactory:
    def _row(self, acc_type: str):
        return {
            "id": 7, "account_number": "5012345678", "user_id": 42,
            "account_type": acc_type, "balance": "1234.50", "status": "active",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC), "holder_name": "X",
        }

    def test_builds_correct_subtypes(self):
        assert isinstance(account_from_row(self._row("savings")), SavingsAccount)
        assert isinstance(account_from_row(self._row("current")), CurrentAccount)

    def test_rejects_unknown_type(self):
        with pytest.raises(ValueError):
            account_from_row(self._row("offshore"))


class TestTxnDirections:
    def test_credit_debit_self(self, make_txn):
        txn = make_txn(from_account_id=1, to_account_id=2)
        assert txn.direction_for({2}) == "credit"
        assert txn.direction_for({1}) == "debit"
        assert txn.direction_for({1, 2}) == "self"

    def test_counterparty(self, make_txn):
        txn = make_txn(from_account_id=1, to_account_id=2)
        object.__setattr__(txn, "from_name", "Rohan Verma")
        assert txn.counterparty_for({2}) == "Rohan Verma"


def test_money_round():
    assert money_round(Decimal("10.005")) == Decimal("10.01")
    assert money_round(Decimal("10.004")) == Decimal("10.00")
