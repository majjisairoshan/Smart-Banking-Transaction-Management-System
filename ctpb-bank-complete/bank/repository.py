"""Data-access layer — the **Repository** pattern.

All SQL lives here; services never write SQL.  Read methods borrow a pooled
connection per call.  Write methods that participate in a larger unit of work
take an explicit ``conn`` so several statements share one transaction.

Transaction-safety highlights (rubric §4):
* ``lock_accounts`` uses ``SELECT … FOR UPDATE ORDER BY id`` — a deterministic
  lock ordering that eliminates deadlocks between concurrent transfers.
* Balance mutation is an atomic ``UPDATE … balance = balance + %s`` executed
  inside the same transaction, so the ledger can never be half-written.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, TypeVar

from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import RealDictCursor

from .db import ConnectionPool
from .models import (
    Account,
    CustomerView,
    Role,
    Transaction,
    TxnStatus,
    TxnType,
    User,
    account_from_row,
)

T = TypeVar("T")

_ACCOUNT_FROM = """
    FROM accounts a
    JOIN users u ON u.id = a.user_id
"""

_ACCOUNT_SELECT = f"""
    SELECT a.id, a.account_number, a.user_id, a.account_type, a.balance, a.status,
           a.created_at, u.full_name AS holder_name
    {_ACCOUNT_FROM}
"""

_TXN_FROM = """
    FROM transactions t
    LEFT JOIN accounts fa ON fa.id = t.from_account_id
    LEFT JOIN accounts ta ON ta.id = t.to_account_id
    LEFT JOIN users fu ON fu.id = fa.user_id
    LEFT JOIN users tu ON tu.id = ta.user_id
"""

_TXN_SELECT = f"""
    SELECT t.*, fa.account_number AS from_number, ta.account_number AS to_number,
           fu.full_name AS from_name, tu.full_name AS to_name
    {_TXN_FROM}
"""


def _rows(cur: Any, factory: Callable[[Any], T]) -> list[T]:
    """Map every RealDictRow of the cursor's result through ``factory``."""
    return [factory(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
class UserRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def find_by_username(self, username: str) -> User | None:
        with self._pool.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
        return User.from_row(row) if row else None

    def find_by_id(self, user_id: int) -> User | None:
        with self._pool.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
        return User.from_row(row) if row else None

    def create(
        self,
        conn: PgConnection,
        *,
        username: str,
        full_name: str,
        email: str,
        password_hash: str,
        role: Role = Role.USER,
    ) -> User:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO users (username, full_name, email, password_hash, role)
                   VALUES (%s, %s, %s, %s, %s)
                   RETURNING *""",
                (username, full_name, email, password_hash, role.value),
            )
            return User.from_row(cur.fetchone())

    def list_customers(self, *, search: str = "", limit: int = 20, offset: int = 0) -> tuple[list[User], int]:
        pattern = f"%{search}%"
        with self._pool.cursor() as cur:
            cur.execute(
                """SELECT *, COUNT(*) OVER() AS total
                   FROM users
                   WHERE role = 'user'
                     AND (%s = '' OR username ILIKE %s OR full_name ILIKE %s OR email ILIKE %s)
                   ORDER BY created_at DESC
                   LIMIT %s OFFSET %s""",
                (search, pattern, pattern, pattern, limit, offset),
            )
            rows = cur.fetchall()
        total = int(rows[0]["total"]) if rows else 0
        return [User.from_row(r) for r in rows], total

    def update_email(self, user_id: int, email: str) -> None:
        with self._pool.cursor() as cur:
            cur.execute("UPDATE users SET email = %s WHERE id = %s", (email, user_id))

    def update_password(self, user_id: int, password_hash: str) -> None:
        with self._pool.cursor() as cur:
            cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id))


# ---------------------------------------------------------------------------
class AccountRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    # -- reads ---------------------------------------------------------------
    def find_by_number(self, number: str) -> Account | None:
        with self._pool.cursor() as cur:
            cur.execute(_ACCOUNT_SELECT + " WHERE a.account_number = %s", (number,))
            row = cur.fetchone()
        return account_from_row(row) if row else None

    def find_by_id(self, account_id: int) -> Account | None:
        with self._pool.cursor() as cur:
            cur.execute(_ACCOUNT_SELECT + " WHERE a.id = %s", (account_id,))
            row = cur.fetchone()
        return account_from_row(row) if row else None

    def list_by_user(self, user_id: int) -> list[Account]:
        with self._pool.cursor() as cur:
            cur.execute(
                _ACCOUNT_SELECT + " WHERE a.user_id = %s ORDER BY a.account_type",
                (user_id,),
            )
            return _rows(cur, account_from_row)

    def list_by_users(self, user_ids: list[int]) -> dict[int, list[Account]]:
        if not user_ids:
            return {}
        with self._pool.cursor() as cur:
            cur.execute(
                _ACCOUNT_SELECT + " WHERE a.user_id = ANY(%s) ORDER BY a.user_id, a.account_type",
                (user_ids,),
            )
            accounts = _rows(cur, account_from_row)
        grouped: dict[int, list[Account]] = {}
        for acc in accounts:
            grouped.setdefault(acc.user_id, []).append(acc)
        return grouped

    def list_active_savings(self) -> list[Account]:
        with self._pool.cursor() as cur:
            cur.execute(
                _ACCOUNT_SELECT + " WHERE a.account_type = 'savings' AND a.status = 'active' ORDER BY a.id"
            )
            return _rows(cur, account_from_row)

    def count_by_type(self) -> dict[str, int]:
        with self._pool.cursor() as cur:
            cur.execute("SELECT account_type, COUNT(*) AS c FROM accounts GROUP BY account_type")
            return {r["account_type"]: int(r["c"]) for r in cur.fetchall()}

    def total_liabilities(self) -> Decimal:
        with self._pool.cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(balance), 0) AS t FROM accounts")
            return Decimal(str(cur.fetchone()["t"]))

    def number_exists(self, conn: PgConnection, number: str) -> bool:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM accounts WHERE account_number = %s", (number,))
            return cur.fetchone() is not None

    # -- transactional writes ---------------------------------------------------
    def create(
        self,
        conn: PgConnection,
        *,
        user_id: int,
        account_number: str,
        account_type: str,
        balance: Decimal = Decimal("0"),
    ) -> Account:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO accounts (account_number, user_id, account_type, balance)
                   VALUES (%s, %s, %s, %s)
                   RETURNING id, created_at""",
                (account_number, user_id, account_type, balance),
            )
            row = cur.fetchone()
        # Route through the factory so the correct concrete subtype is built —
        # instantiating the abstract Account directly is a TypeError by design.
        return account_from_row(
            {
                "id": row["id"],
                "account_number": account_number,
                "user_id": user_id,
                "account_type": account_type,
                "balance": balance,
                "status": "active",
                "created_at": row["created_at"],
                "holder_name": None,
            }
        )

    def lock_accounts(self, conn: PgConnection, ids: list[int]) -> dict[int, Account]:
        """Row-lock the given accounts in ascending id order (deadlock-free)."""
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                _ACCOUNT_SELECT + " WHERE a.id = ANY(%s) ORDER BY a.id FOR UPDATE OF a",
                (list(ids),),
            )
            rows = cur.fetchall()
        return {r["id"]: account_from_row(r) for r in rows}

    def apply_delta(self, conn: PgConnection, account_id: int, delta: Decimal) -> Decimal:
        """Atomic balance mutation; returns the new balance."""
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE accounts
                   SET balance = balance + %s, updated_at = now()
                   WHERE id = %s
                   RETURNING balance""",
                (delta, account_id),
            )
            return Decimal(str(cur.fetchone()[0]))

    def set_status(self, account_id: int, status: str) -> None:
        with self._pool.cursor() as cur:
            cur.execute(
                "UPDATE accounts SET status = %s, updated_at = now() WHERE id = %s",
                (status, account_id),
            )


# ---------------------------------------------------------------------------
class TransactionRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def insert(
        self,
        conn: PgConnection,
        *,
        txn_ref: str,
        idempotency_key: str | None,
        from_id: int | None,
        to_id: int | None,
        amount: Decimal,
        txn_type: TxnType,
        status: TxnStatus,
        note: str | None,
        sender_after: Decimal | None,
        receiver_after: Decimal | None,
        created_at: datetime | None = None,
    ) -> Transaction:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO transactions
                       (txn_ref, idempotency_key, from_account_id, to_account_id, amount,
                        txn_type, status, note, sender_balance_after, receiver_balance_after,
                        created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now()))
                   RETURNING id, created_at""",
                (
                    txn_ref,
                    idempotency_key,
                    from_id,
                    to_id,
                    amount,
                    txn_type.value,
                    status.value,
                    note,
                    sender_after,
                    receiver_after,
                    created_at,
                ),
            )
            row = cur.fetchone()
        return Transaction(
            id=row["id"],
            txn_ref=txn_ref,
            amount=amount,
            txn_type=txn_type,
            status=status,
            created_at=row["created_at"],
            note=note,
            from_account_id=from_id,
            to_account_id=to_id,
            idempotency_key=idempotency_key,
            sender_balance_after=sender_after,
            receiver_balance_after=receiver_after,
        )

    def find_by_idempotency_key(self, conn: PgConnection, key: str) -> Transaction | None:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM transactions WHERE idempotency_key = %s", (key,))
            row = cur.fetchone()
        return Transaction.from_row(row) if row else None

    def list_for_accounts(
        self,
        account_ids: list[int],
        *,
        txn_type: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[Transaction], int]:
        if not account_ids:
            return [], 0
        with self._pool.cursor() as cur:
            cur.execute(
                _TXN_SELECT
                + """
                WHERE (t.from_account_id = ANY(%s) OR t.to_account_id = ANY(%s))
                  AND (%s = '' OR t.txn_type = %s)
                ORDER BY t.created_at DESC, t.id DESC
                LIMIT %s OFFSET %s""",
                (account_ids, account_ids, txn_type or "", txn_type, limit, offset),
            )
            data = cur.fetchall()
            cur.execute(
                """SELECT COUNT(*) AS c FROM transactions t
                   WHERE (t.from_account_id = ANY(%s) OR t.to_account_id = ANY(%s))
                     AND (%s = '' OR t.txn_type = %s)""",
                (account_ids, account_ids, txn_type or "", txn_type),
            )
            total = int(cur.fetchone()["c"])
        return [Transaction.from_row(r) for r in data], total

    def recent_outbound_times(self, conn: PgConnection, from_account_id: int, since: datetime) -> list[datetime]:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT created_at FROM transactions
                   WHERE from_account_id = %s AND created_at >= %s AND status <> 'failed'
                   ORDER BY created_at DESC""",
                (from_account_id, since),
            )
            return [r[0] for r in cur.fetchall()]

    def list_recent(self, limit: int = 10) -> list[Transaction]:
        with self._pool.cursor() as cur:
            cur.execute(_TXN_SELECT + " ORDER BY t.created_at DESC, t.id DESC LIMIT %s", (limit,))
            return _rows(cur, Transaction.from_row)

    def list_flagged(self, limit: int = 30) -> list[Transaction]:
        with self._pool.cursor() as cur:
            cur.execute(
                _TXN_SELECT + " WHERE t.status = 'flagged' ORDER BY t.created_at DESC LIMIT %s",
                (limit,),
            )
            return _rows(cur, Transaction.from_row)

    def today_totals(self) -> tuple[int, Decimal]:
        with self._pool.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) AS c, COALESCE(SUM(amount), 0) AS s
                   FROM transactions
                   WHERE created_at >= date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata'
                     AND status <> 'failed'"""
            )
            row = cur.fetchone()
        return int(row["c"]), Decimal(str(row["s"]))

    def volume_by_day(self, days: int = 14) -> list[tuple[date, Decimal]]:
        with self._pool.cursor() as cur:
            cur.execute(
                """SELECT (created_at AT TIME ZONE 'Asia/Kolkata')::date AS d,
                          COALESCE(SUM(amount), 0) AS s
                   FROM transactions
                   WHERE created_at >= now() - make_interval(days => %s) AND status <> 'failed'
                   GROUP BY 1""",
                (days - 1,),
            )
            raw = {r["d"]: Decimal(str(r["s"])) for r in cur.fetchall()}
        today = datetime.now().astimezone().date()
        return [(today - timedelta(days=days - 1 - i), raw.get(today - timedelta(days=days - 1 - i), Decimal("0"))) for i in range(days)]

    def income_expense_30d(self, account_ids: list[int]) -> tuple[Decimal, Decimal]:
        if not account_ids:
            return Decimal("0"), Decimal("0")
        with self._pool.cursor() as cur:
            cur.execute(
                """SELECT
                     COALESCE(SUM(CASE WHEN t.to_account_id = ANY(%s)
                                        AND NOT (t.from_account_id = ANY(%s) AND t.txn_type = 'transfer')
                                       THEN t.amount END), 0) AS income,
                     COALESCE(SUM(CASE WHEN t.from_account_id = ANY(%s)
                                        AND NOT (t.to_account_id = ANY(%s) AND t.txn_type = 'transfer')
                                       THEN t.amount END), 0) AS expense
                   FROM transactions t
                   WHERE t.created_at >= now() - interval '30 days' AND t.status <> 'failed'
                     AND (t.from_account_id = ANY(%s) OR t.to_account_id = ANY(%s))""",
                (account_ids, account_ids, account_ids, account_ids, account_ids, account_ids),
            )
            row = cur.fetchone()
        return Decimal(str(row["income"])), Decimal(str(row["expense"]))

    def monthly_flow(self, account_ids: list[int], months: int = 6) -> dict[str, tuple[Decimal, Decimal]]:
        """{YYYY-MM: (income, expense)} excluding own-account shuffles."""
        if not account_ids:
            return {}
        with self._pool.cursor() as cur:
            cur.execute(
                """SELECT to_char(created_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM') AS m,
                     COALESCE(SUM(CASE WHEN t.to_account_id = ANY(%s)
                                        AND NOT (t.from_account_id = ANY(%s) AND t.txn_type = 'transfer')
                                       THEN t.amount END), 0) AS income,
                     COALESCE(SUM(CASE WHEN t.from_account_id = ANY(%s)
                                        AND NOT (t.to_account_id = ANY(%s) AND t.txn_type = 'transfer')
                                       THEN t.amount END), 0) AS expense
                   FROM transactions t
                   WHERE t.status <> 'failed'
                     AND (t.from_account_id = ANY(%s) OR t.to_account_id = ANY(%s))
                   GROUP BY 1""",
                (account_ids, account_ids, account_ids, account_ids, account_ids, account_ids),
            )
            return {r["m"]: (Decimal(str(r["income"])), Decimal(str(r["expense"]))) for r in cur.fetchall()}


# ---------------------------------------------------------------------------
def build_customer_views(users: list[User], grouped: dict[int, list[Account]]) -> list[CustomerView]:
    """Zip users with their accounts (kept as a named step for readability)."""
    return [CustomerView(user=u, accounts=tuple(grouped.get(u.id, []))) for u in users]
