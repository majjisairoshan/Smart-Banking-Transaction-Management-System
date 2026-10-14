"""Integration test against a real PostgreSQL database.

Skipped by default; enable with:
    TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ctpbd_test pytest -m integration
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest

pytestmark = pytest.mark.integration
DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL not set")
class TestTransferAgainstRealPostgres:
    @pytest.fixture(scope="class")
    def services(self):
        from bank.config import Config
        from bank.db import ConnectionPool, ensure_schema
        from bank.services import AdminService, BankingService

        ConnectionPool.reset()
        cfg = Config(database_url=DATABASE_URL, db_pool_max=4)
        pool = ConnectionPool.initialize(cfg.dsn, 1, 4)
        ensure_schema(pool)
        yield AdminService(pool, cfg), BankingService(pool, cfg), pool
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("TRUNCATE transactions, accounts, users RESTART IDENTITY CASCADE")
        ConnectionPool.reset()

    def test_full_transfer_cycle(self, services):
        from bank.services import InsufficientFundsError

        admin, banking, _pool = services
        tag = uuid.uuid4().hex[:6]
        alice = admin.create_customer(
            full_name="Alice Test", username=f"alice.{tag}", email=f"alice.{tag}@t.in",
            password="password123", account_types=["savings"], opening_balance=Decimal("9000"),
        )
        bob = admin.create_customer(
            full_name="Bob Test", username=f"bob.{tag}", email=f"bob.{tag}@t.in",
            password="password123", account_types=["current"], opening_balance=Decimal("100"),
        )
        src, dst = alice.accounts[0], bob.accounts[0]

        key = uuid.uuid4().hex
        res = banking.transfer(
            sender=alice.user, from_account_id=src.id, to_account_number=dst.account_number,
            amount=Decimal("2500.00"), note="integration", idempotency_key=key,
        )
        assert res.transaction.status.value == "success"

        # --- idempotency: exact retry returns the original, debits nothing twice
        replay = banking.transfer(
            sender=alice.user, from_account_id=src.id, to_account_number=dst.account_number,
            amount=Decimal("2500.00"), note="integration", idempotency_key=key,
        )
        assert replay.duplicate and replay.transaction.id == res.transaction.id

        # --- balances reflect exactly one debit/credit (conservation)
        assert Decimal(banking.balance_payload(alice.user)["accounts"][0]["balance"]) == Decimal("6500.00")
        assert Decimal(banking.balance_payload(bob.user)["accounts"][0]["balance"]) == Decimal("2600.00")

        # --- invariant enforcement hits the DB floor, not just Python
        with pytest.raises(InsufficientFundsError):
            banking.transfer(
                sender=alice.user, from_account_id=src.id, to_account_number=dst.account_number,
                amount=Decimal("8000.00"), note="too much", idempotency_key=uuid.uuid4().hex,
            )

        # --- validation endpoint sees the real row
        v = banking.validate_account(dst.account_number)
        assert v.found and v.holder_name == "Bob Test" and v.account_type == "current"
