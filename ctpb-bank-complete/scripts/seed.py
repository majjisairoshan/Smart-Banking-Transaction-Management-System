"""Bootstrap the CTPBD database: create it (optionally), ensure schema, seed demo data.

    python -m scripts.seed --create-db --seed

The seed builds a *consistent ledger*: it generates a timeline of events
(opening deposits, salary credits, transfers, a couple of large flagged
transfers, interest credits), replays them in memory honouring the same
account invariants as production code, and then writes final balances plus
the full transaction history in a single transaction.
"""
from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg2

from bank.config import Config
from bank.db import ConnectionPool, ensure_schema
from bank.models import CurrentAccount, Role, SavingsAccount, TxnStatus, TxnType
from bank.repository import AccountRepository, UserRepository
from bank.security import hash_password
from bank.utils import new_account_number, new_txn_ref

UTC = UTC

CUSTOMER_SPECS = [
    ("aarav.sharma", "Aarav Sharma", "aarav.sharma@example.in", ("savings", "current")),
    ("priya.nair", "Priya Nair", "priya.nair@example.in", ("savings", "current")),
    ("rohan.verma", "Rohan Verma", "rohan.verma@example.in", ("savings", "current")),
    ("meera.iyer", "Meera Iyer", "meera.iyer@example.in", ("savings",)),
    ("karan.malhotra", "Karan Malhotra", "karan.malhotra@example.in", ("current",)),
]


@dataclass
class _Evt:
    ts: datetime
    kind: str  # deposit | transfer | interest
    src: int | None
    dst: int
    amount: Decimal
    note: str


def create_database(cfg: Config) -> bool:
    """CREATE DATABASE CTPBD if it doesn't exist. Returns True when created."""
    conn = psycopg2.connect(cfg.maintenance_dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (cfg.db_name,))
            if cur.fetchone():
                return False
            cur.execute(f'CREATE DATABASE "{cfg.db_name}"')
            return True
    finally:
        conn.close()


def seed(pool: ConnectionPool) -> str:
    users = UserRepository(pool)
    accounts = AccountRepository(pool)

    if users.find_by_username("admin"):
        return "already seeded — nothing to do"

    rng = random.Random(42)
    now = datetime.now(UTC).replace(microsecond=0)
    start = now - timedelta(days=26)

    with pool.connection() as conn:
        users.create(
            conn,
            username="admin",
            full_name="Priya Deshmukh",
            email="admin@ctpb.in",
            password_hash=hash_password("Admin@123"),
            role=Role.ADMIN,
        )

        def unique_number() -> str:
            while True:
                n = new_account_number()
                if not accounts.number_exists(conn, n):
                    return n

        acc_type: dict[int, str] = {}
        balance: dict[int, Decimal] = {}
        opened_at: dict[int, datetime] = {}
        events: list[_Evt] = []
        acc_ids: list[int] = []

        for username, full_name, email, types in CUSTOMER_SPECS:
            user = users.create(
                conn,
                username=username,
                full_name=full_name,
                email=email,
                password_hash=hash_password("User@123"),
            )
            for j, kind in enumerate(types):
                acc = accounts.create(
                    conn,
                    user_id=user.id,
                    account_number=unique_number(),
                    account_type=kind,
                    balance=Decimal("0"),
                )
                acc_type[acc.id] = kind
                balance[acc.id] = Decimal("0")
                acc_ids.append(acc.id)
                opening_ts = start + timedelta(hours=rng.randint(2, 40)) + timedelta(minutes=j * 17)
                opened_at[acc.id] = opening_ts
                opening = (
                    Decimal(rng.randrange(250, 900, 25)) * 100
                    if kind == "savings"
                    else Decimal(rng.randrange(600, 2600, 50)) * 100
                )
                events.append(_Evt(opening_ts, "deposit", None, acc.id, opening, "Opening balance"))

        def floor_of(aid: int) -> Decimal:
            return SavingsAccount.MIN_BALANCE if acc_type[aid] == "savings" else -CurrentAccount.OVERDRAFT_LIMIT

        # Salary credits make the charts look like real life.
        for day in (7, 14, 21):
            for aid in acc_ids:
                if acc_type[aid] == "savings":
                    events.append(
                        _Evt(start + timedelta(days=day, hours=10), "deposit", None, aid,
                             Decimal(85000), "Salary credit — ACME Systems")
                    )

        # Everyday transfers between customers (respecting account invariants).
        for _ in range(52):
            ts = start + timedelta(days=rng.randint(1, 25), hours=rng.randint(8, 21), minutes=rng.randint(0, 59))
            src, dst = rng.sample(acc_ids, 2)
            amount = Decimal(rng.randrange(2, 180)) * 50  # ₹100 – ₹9,000
            if balance[src] - amount < floor_of(src):
                continue
            note = rng.choice(["UPI payment", "Rent share", "Dinner split", "Invoice settlement",
                               "Movie tickets", "Grocery run", "Freelance payout", "EMI contribution"])
            events.append(_Evt(ts, "transfer", src, dst, amount, note))

        # A loan disbursement on one current account funds two large transfers
        # that exercise the fraud-flag path — always within the overdraft floor.
        for aid in acc_ids:
            if acc_type[aid] == "current":
                others = [x for x in acc_ids if x != aid]
                events.append(_Evt(now - timedelta(days=3, hours=2), "deposit", None, aid,
                                   Decimal("400000"), "Term loan disbursement"))
                events.append(_Evt(now - timedelta(days=2, hours=3), "transfer", aid,
                                   rng.choice(others), Decimal("150000"), "Equipment purchase"))
                events.append(_Evt(now - timedelta(days=1, hours=5), "transfer", aid,
                                   rng.choice(others), Decimal("120500"), "Vendor advance"))
                break

        # Interest credits on savings, halfway through the window.
        for aid in acc_ids:
            if acc_type[aid] == "savings":
                interest = (balance[aid] * SavingsAccount.ANNUAL_RATE / 12).quantize(Decimal("0.01"))
                if interest > 0:
                    events.append(_Evt(start + timedelta(days=13), "interest", None, aid,
                                       interest, "Savings interest"))
        # NOTE: balance[] reflects opening+salary only so far for interest calc; fine for a seed.

        # ---- Phase 1: replay in memory, enforcing the production invariants ----
        events.sort(key=lambda e: e.ts)
        applied: list[tuple[_Evt, Decimal | None, Decimal]] = []
        for evt in events:
            if evt.kind == "transfer":
                assert evt.src is not None
                if balance[evt.src] - evt.amount < floor_of(evt.src):
                    continue  # invariant guard — never write an illegal state
                balance[evt.src] -= evt.amount
                balance[evt.dst] += evt.amount
                applied.append((evt, balance[evt.src], balance[evt.dst]))
            else:
                balance[evt.dst] += evt.amount
                applied.append((evt, None, balance[evt.dst]))

        # ---- Phase 2: persist the (guaranteed legal) ledger --------------------
        skipped = len(events) - len(applied)
        with conn.cursor() as cur:
            for evt, sender_after, receiver_after in applied:
                flagged = evt.amount >= Decimal("100000") and evt.kind == "transfer"
                status = TxnStatus.FLAGGED if flagged else TxnStatus.SUCCESS
                if evt.kind == "transfer":
                    assert evt.src is not None
                    cur.execute(
                        """INSERT INTO transactions
                               (txn_ref, from_account_id, to_account_id, amount, txn_type, status,
                                note, sender_balance_after, receiver_balance_after, created_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (new_txn_ref(), evt.src, evt.dst, evt.amount, TxnType.TRANSFER.value,
                         status.value, evt.note, sender_after, receiver_after, evt.ts),
                    )
                else:
                    cur.execute(
                        """INSERT INTO transactions
                               (txn_ref, from_account_id, to_account_id, amount, txn_type, status,
                                note, receiver_balance_after, created_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (new_txn_ref(), None, evt.dst, evt.amount,
                         (TxnType.DEPOSIT if evt.kind == "deposit" else TxnType.INTEREST).value,
                         status.value, evt.note, receiver_after, evt.ts),
                    )
            for aid, bal in balance.items():
                cur.execute(
                    "UPDATE accounts SET balance = %s, created_at = %s WHERE id = %s",
                    (bal, opened_at[aid], aid),
                )

    return (
        f"seeded {len(CUSTOMER_SPECS)} customers, {len(acc_ids)} accounts, "
        f"{len(applied)} transactions ({skipped} invariant-skipped)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the CTPBD database")
    parser.add_argument("--create-db", action="store_true", help="CREATE DATABASE CTPBD if missing")
    parser.add_argument("--seed", action="store_true", help="insert demo data if the DB is empty")
    args = parser.parse_args(argv)

    cfg = Config.from_env()
    if args.create_db:
        created = create_database(cfg)
        print(f"[seed] database {cfg.db_name}: {'created' if created else 'already exists'}")

    ConnectionPool.reset()
    pool = ConnectionPool.initialize(cfg.dsn, 1, 4)
    ensure_schema(pool)
    print("[seed] schema ensured (tables + indexes)")

    if args.seed:
        print(f"[seed] {seed(pool)}")
        print()
        print("  Demo credentials")
        print("  ----------------")
        print("  Admin portal    : admin / Admin@123")
        print("  Customer portal : aarav.sharma / User@123")
        print("  More customers  : priya.nair, rohan.verma, meera.iyer, karan.malhotra (all User@123)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
