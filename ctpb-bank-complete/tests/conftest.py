"""Shared fixtures & factories — pure in-memory domain objects (no DB needed)."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from bank.models import (
    AccountStatus,
    CurrentAccount,
    SavingsAccount,
    Transaction,
    TxnStatus,
    TxnType,
)

UTC = UTC
NOW = datetime(2026, 10, 12, 9, 30, tzinfo=UTC)


@pytest.fixture
def make_savings():
    def _make(balance: str = "5000.00", status: AccountStatus = AccountStatus.ACTIVE, **kw) -> SavingsAccount:
        return SavingsAccount(
            id=kw.get("id", 1),
            account_number=kw.get("number", "5000000001"),
            user_id=kw.get("user_id", 10),
            balance=Decimal(balance),
            status=status,
            created_at=NOW,
            holder_name="Aarav Sharma",
        )
    return _make


@pytest.fixture
def make_current():
    def _make(balance: str = "20000.00", status: AccountStatus = AccountStatus.ACTIVE, **kw) -> CurrentAccount:
        return CurrentAccount(
            id=kw.get("id", 2),
            account_number=kw.get("number", "5000000002"),
            user_id=kw.get("user_id", 11),
            balance=Decimal(balance),
            status=status,
            created_at=NOW,
            holder_name="Priya Nair",
        )
    return _make


@pytest.fixture
def make_txn():
    def _make(**kw) -> Transaction:
        return Transaction(
            id=kw.get("id", 1),
            txn_ref=kw.get("txn_ref", "TXNTEST000000001"),
            amount=Decimal(kw.get("amount", "100.00")),
            txn_type=kw.get("txn_type", TxnType.TRANSFER),
            status=kw.get("status", TxnStatus.SUCCESS),
            created_at=kw.get("created_at", NOW),
            from_account_id=kw.get("from_account_id", 1),
            to_account_id=kw.get("to_account_id", 2),
        )
    return _make
