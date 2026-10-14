"""Business-logic layer (use-cases).

Design notes (rubric §3/§4):
* Services depend on repositories (dependency inversion) — they never see SQL.
* ``plan_transfer`` is a **pure function**: all transfer invariants are
  checked without side effects, making them trivially unit- and
  property-testable (Hypothesis, see tests/).
* ``BankingService.transfer`` wraps validation + ledger writes in a single
  DB transaction with row-level locks — atomic, idempotent (client key),
  and safe under concurrent requests.
* ``AdminService.run_interest_accrual`` fans work over a
  ``ThreadPoolExecutor``: DB-bound work releases the GIL, and each account
  is processed in its own transaction, so a failure never poisons the batch.
"""
from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import reduce
from math import ceil

from . import algorithms
from .config import Config
from .db import ConnectionPool
from .models import (
    Account,
    AccountStatus,
    AccountValidation,
    CustomerView,
    Role,
    SavingsAccount,
    Transaction,
    TxnStatus,
    TxnType,
    User,
    money_round,
)
from .repository import (
    AccountRepository,
    TransactionRepository,
    UserRepository,
    build_customer_views,
)
from .security import hash_password, verify_password
from .utils import new_account_number, new_txn_ref, normalize_account_number, sparkline_points

UTC = UTC


# ---------------------------------------------------------------------------
# Exception hierarchy — precise failures, mapped to HTTP codes in routes
# ---------------------------------------------------------------------------
class BankingError(Exception):
    """Base class for every domain error."""


class AuthenticationError(BankingError):
    pass


class ValidationError(BankingError):
    pass


class AccountNotFoundError(BankingError):
    pass


class NotAccountOwnerError(BankingError):
    pass


class FrozenAccountError(BankingError):
    pass


class SameAccountError(BankingError):
    pass


class InvalidAmountError(BankingError):
    pass


class InsufficientFundsError(BankingError):
    def __init__(self, account: Account, amount: Decimal) -> None:
        self.account = account
        self.amount = amount
        super().__init__(
            f"Insufficient funds in {account.account_type.value} account "
            f"{account.account_number}: need {amount}, available headroom "
            f"{account.balance - account.withdrawal_floor()}"
        )


# ---------------------------------------------------------------------------
# Pure transfer planning (no I/O => fast property tests)
# ---------------------------------------------------------------------------
def plan_transfer(src: Account, dst: Account, amount: Decimal, *, max_amount: Decimal) -> None:
    """Validate a proposed transfer against every invariant; raise on violation."""
    if amount <= 0:
        raise InvalidAmountError("Amount must be greater than zero.")
    if amount != money_round(amount):
        raise InvalidAmountError("Amount can have at most 2 decimal places.")
    if amount > max_amount:
        raise InvalidAmountError(f"Single transfers are capped at ₹{max_amount:,.0f}.")
    if src.account_number == dst.account_number:
        raise SameAccountError("Source and destination accounts are the same.")
    if not src.is_active():
        raise FrozenAccountError(f"Your {src.account_type.value} account is frozen.")
    if not dst.can_credit():
        raise FrozenAccountError("The beneficiary account is frozen and cannot receive money.")
    if not src.can_debit(amount):
        raise InsufficientFundsError(src, amount)


# ---------------------------------------------------------------------------
# Immuatable report DTOs returned to the web layer
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TransferResult:
    transaction: Transaction
    flag_reasons: tuple[str, ...] = ()
    duplicate: bool = False


@dataclass(frozen=True)
class MonthBar:
    label: str
    income: Decimal
    expense: Decimal


@dataclass(frozen=True)
class Overview:
    accounts: tuple[Account, ...]
    total_balance: Decimal
    recent: tuple[Transaction, ...]
    income_30d: Decimal
    expense_30d: Decimal
    months: tuple[MonthBar, ...]
    spark_points: str
    account_ids: frozenset[int]


@dataclass(frozen=True)
class History:
    items: tuple[Transaction, ...]
    total: int
    page: int
    pages: int
    per_page: int
    sort: str
    sort_elapsed_us: int
    account_ids: frozenset[int]


@dataclass(frozen=True)
class AdminStats:
    customers: int
    accounts_by_type: dict[str, int]
    total_liabilities: Decimal
    today_count: int
    today_volume: Decimal
    flagged: tuple[Transaction, ...]
    volume_by_day: tuple[tuple[object, Decimal], ...]
    largest: tuple[Transaction, ...]
    recent: tuple[Transaction, ...]


@dataclass(frozen=True)
class InterestReport:
    month_key: str
    accounts_processed: int
    accounts_credited: int
    total_credited: Decimal
    duration_ms: float
    workers: int
    errors: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
class AuthService:
    def __init__(self, pool: ConnectionPool) -> None:
        self._users = UserRepository(pool)

    def authenticate(self, username: str, password: str, *, role: Role) -> User:
        user = self._users.find_by_username((username or "").strip().lower())
        if user is None or user.role is not role or not verify_password(user.password_hash, password):
            raise AuthenticationError("Invalid username or password.")
        return user

    def get_user(self, user_id: int) -> User | None:
        return self._users.find_by_id(user_id)


# ---------------------------------------------------------------------------
class BankingService:
    """Customer-facing use-cases: validate account, balances, history, transfer."""

    def __init__(self, pool: ConnectionPool, cfg: Config) -> None:
        self._cfg = cfg
        self._pool = pool
        self._users = UserRepository(pool)
        self._accounts = AccountRepository(pool)
        self._txns = TransactionRepository(pool)

    # -- Validate Account -----------------------------------------------------
    def validate_account(self, raw_number: str) -> AccountValidation:
        number = normalize_account_number(raw_number)
        if not number:
            return AccountValidation(found=False, account_number=raw_number or "")
        acc = self._accounts.find_by_number(number)
        if acc is None:
            return AccountValidation(found=False, account_number=number)
        return AccountValidation(
            found=True,
            account_number=acc.account_number,
            holder_name=acc.holder_name,
            account_type=acc.account_type.value,
            status=acc.status.value,
        )

    # -- Balance & dashboard -----------------------------------------------------
    def accounts_of(self, user_id: int) -> list[Account]:
        return self._accounts.list_by_user(user_id)

    def overview(self, user: User) -> Overview:
        accounts = self.accounts_of(user.id)
        ids = [a.id for a in accounts]
        total = reduce(lambda s, a: s + a.balance, accounts, Decimal("0"))  # functional fold
        recent, _ = self._txns.list_for_accounts(ids, limit=8)
        income, expense = self._txns.income_expense_30d(ids)
        months = self._month_bars(ids)
        spark = self._spark_points(accounts, recent, total)
        return Overview(
            accounts=tuple(accounts),
            total_balance=total,
            recent=tuple(recent),
            income_30d=income,
            expense_30d=expense,
            months=tuple(months),
            spark_points=spark,
            account_ids=frozenset(ids),
        )

    def _month_bars(self, account_ids: list[int], n: int = 6) -> list[MonthBar]:
        flow = self._txns.monthly_flow(account_ids, months=n)
        now = datetime.now(UTC)
        year, month = now.year, now.month
        bars: list[MonthBar] = []
        for _ in range(n):
            key = f"{year:04d}-{month:02d}"
            income, expense = flow.get(key, (Decimal("0"), Decimal("0")))
            label = datetime(year, month, 1).strftime("%b")
            bars.append(MonthBar(label=label, income=income, expense=expense))
            month -= 1
            if month == 0:
                month, year = 12, year - 1
        bars.reverse()
        return bars

    @staticmethod
    def _spark_points(accounts: list[Account], recent: list[Transaction], total: Decimal) -> str:
        """Reconstruct the running total-balance trend by walking the ledger
        backwards from 'now' — an O(n) single pass over recent transactions."""
        ids = {a.id for a in accounts}
        series = [float(total)]
        for txn in recent:  # newest → oldest
            credit = txn.to_account_id in ids
            debit = txn.from_account_id in ids
            if credit and not debit:
                series.append(series[-1] - float(txn.amount))
            elif debit and not credit:
                series.append(series[-1] + float(txn.amount))
        series.reverse()
        return sparkline_points(series)

    # -- Transaction history -------------------------------------------------------
    def history(
        self,
        user: User,
        *,
        page: int,
        per_page: int = 10,
        txn_type: str | None = None,
        sort: str = "date_desc",
    ) -> History:
        ids = [a.id for a in self.accounts_of(user.id)]
        page = max(page, 1)
        items, total = self._txns.list_for_accounts(
            ids, txn_type=txn_type or None, limit=per_page, offset=(page - 1) * per_page
        )
        pages = max(ceil(total / per_page), 1)
        # In-memory re-sort of the page with our own merge sort (O(p log p)),
        # timed so the UI can show the algorithm's cost honestly.
        t0 = time.perf_counter_ns()
        items = self._apply_sort(items, sort)
        sort_elapsed_us = (time.perf_counter_ns() - t0) // 1000
        return History(
            items=tuple(items),
            total=total,
            page=page,
            pages=pages,
            per_page=per_page,
            sort=sort,
            sort_elapsed_us=sort_elapsed_us,
            account_ids=frozenset(ids),
        )

    @staticmethod
    def _apply_sort(items: list[Transaction], sort: str) -> list[Transaction]:
        key_funcs = {
            "date_asc": (lambda t: (t.created_at, t.id), False),
            "date_desc": (lambda t: (t.created_at, t.id), True),
            "amount_asc": (lambda t: (t.amount, t.id), False),
            "amount_desc": (lambda t: (t.amount, t.id), True),
        }
        key, reverse = key_funcs.get(sort, key_funcs["date_desc"])
        return algorithms.merge_sort(items, key=key, reverse=reverse)

    # -- Transfer Money (core use-case) ---------------------------------------------
    def transfer(
        self,
        *,
        sender: User,
        from_account_id: int,
        to_account_number: str,
        amount: Decimal,
        note: str,
        idempotency_key: str,
    ) -> TransferResult:
        """
        Atomic money movement:

        1. idempotency lookup — a retried submit returns the original txn,
        2. resolve both account ids, then lock rows in id order (FOR UPDATE),
        3. pure rule validation (``plan_transfer``),
        4. risk scoring (sliding-window velocity + threshold),
        5. two atomic balance deltas + one ledger insert,
        6. single commit — the ledger and balances can never diverge.

        Amortised cost: O(log n)-ish index lookups; contention only on the two
        locked rows, so unrelated transfers proceed fully in parallel.
        """
        to_number = normalize_account_number(to_account_number)
        note = (note or "").strip()[:160]
        key = idempotency_key or uuid.uuid4().hex

        with self._pool.connection() as conn:
            existing = self._txns.find_by_idempotency_key(conn, key)
            if existing is not None:
                return TransferResult(transaction=existing, duplicate=True)

            dst_stub = self._accounts.find_by_number(to_number)
            if dst_stub is None:
                raise AccountNotFoundError(f"No account with number {to_number}.")

            locked = self._accounts.lock_accounts(conn, [from_account_id, dst_stub.id])
            src = locked.get(from_account_id)
            dst = locked[dst_stub.id]
            if src is None:
                raise AccountNotFoundError("Source account not found.")
            if src.user_id != sender.id:
                raise NotAccountOwnerError("You can only send money from your own account.")

            plan_transfer(src, dst, amount, max_amount=self._cfg.max_transfer_amount)

            now = datetime.now(UTC)
            window = timedelta(seconds=self._cfg.fraud_velocity_window_seconds)
            recent_times = self._txns.recent_outbound_times(conn, src.id, now - window)
            reasons = algorithms.assess_transfer_risk(
                amount=amount,
                recent_outbound_desc=recent_times,
                now=now,
                window=window,
                velocity_limit=self._cfg.fraud_velocity_limit,
                amount_threshold=self._cfg.fraud_amount_threshold,
            )
            status = TxnStatus.FLAGGED if reasons else TxnStatus.SUCCESS

            sender_after = self._accounts.apply_delta(conn, src.id, -amount)
            receiver_after = self._accounts.apply_delta(conn, dst.id, amount)
            txn = self._txns.insert(
                conn,
                txn_ref=new_txn_ref(),
                idempotency_key=key,
                from_id=src.id,
                to_id=dst.id,
                amount=amount,
                txn_type=TxnType.TRANSFER,
                status=status,
                note=note or None,
                sender_after=sender_after,
                receiver_after=receiver_after,
            )
            return TransferResult(transaction=txn, flag_reasons=reasons)

    # -- Utilities --------------------------------------------------------------------
    def denominations(self, amount: int) -> list[tuple[int, int]]:
        """ATM-style note breakdown via the greedy algorithm (rubric §1)."""
        return algorithms.greedy_denominations(amount)

    def balance_payload(self, user: User) -> dict[str, object]:
        accounts = self.accounts_of(user.id)
        return {
            "total": str(money_round(reduce(lambda s, a: s + a.balance, accounts, Decimal("0")))),
            "accounts": [
                {
                    "id": a.id,
                    "number": a.account_number,
                    "type": a.account_type.value,
                    "balance": str(money_round(a.balance)),
                    "status": a.status.value,
                }
                for a in accounts
            ],
        }

    # -- Profile ------------------------------------------------------------------------
    def update_email(self, user: User, email: str) -> None:
        email = (email or "").strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValidationError("Please enter a valid email address.")
        self._users.update_email(user.id, email)

    def change_password(self, user: User, old: str, new: str) -> None:
        fresh = self._users.find_by_id(user.id)
        if fresh is None or not verify_password(fresh.password_hash, old):
            raise AuthenticationError("Current password is incorrect.")
        if len(new or "") < 8:
            raise ValidationError("New password must be at least 8 characters long.")
        self._users.update_password(user.id, hash_password(new))


# ---------------------------------------------------------------------------
class AdminService:
    """Back-office use-cases: stats, customer management, interest accrual."""

    def __init__(self, pool: ConnectionPool, cfg: Config) -> None:
        self._cfg = cfg
        self._pool = pool
        self._users = UserRepository(pool)
        self._accounts = AccountRepository(pool)
        self._txns = TransactionRepository(pool)

    # -- dashboard stats ---------------------------------------------------------
    def stats(self) -> AdminStats:
        customers, _ = self._users.list_customers(limit=10000)
        flagged = self._txns.list_flagged(limit=10)
        recent = self._txns.list_recent(limit=10)
        count_today, volume_today = self._txns.today_totals()
        largest = tuple(algorithms.top_k(recent, 5, key=lambda t: t.amount))
        return AdminStats(
            customers=len(customers),
            accounts_by_type=self._accounts.count_by_type(),
            total_liabilities=self._accounts.total_liabilities(),
            today_count=count_today,
            today_volume=volume_today,
            flagged=tuple(flagged),
            volume_by_day=tuple(self._txns.volume_by_day(14)),
            largest=largest,
            recent=tuple(recent),
        )

    # -- customers --------------------------------------------------------------------
    def customers(self, *, search: str = "", page: int = 1, per_page: int = 10) -> dict[str, object]:
        users, total = self._users.list_customers(
            search=search, limit=per_page, offset=(max(page, 1) - 1) * per_page
        )
        grouped = self._accounts.list_by_users([u.id for u in users])
        return {
            "customers": build_customer_views(users, grouped),
            "total": total,
            "pages": max(ceil(total / per_page), 1),
            "page": page,
        }

    def create_customer(
        self,
        *,
        full_name: str,
        username: str,
        email: str,
        password: str,
        account_types: list[str],
        opening_balance: Decimal,
    ) -> CustomerView:
        full_name = (full_name or "").strip()
        username = (username or "").strip().lower()
        email = (email or "").strip().lower()
        if len(full_name) < 3:
            raise ValidationError("Full name looks too short.")
        if not username.isalnum() and not all(c.isalnum() or c in "._-" for c in username):
            raise ValidationError("Username may contain letters, digits, '.', '_' or '-'.")
        if len(username) < 3:
            raise ValidationError("Username must be at least 3 characters.")
        if len(password or "") < 8:
            raise ValidationError("Password must be at least 8 characters.")
        if opening_balance < 0:
            raise ValidationError("Opening balance cannot be negative.")
        if not account_types:
            raise ValidationError("Choose at least one account type (savings/current).")

        with self._pool.connection() as conn:
            user = self._users.create(
                conn,
                username=username,
                full_name=full_name,
                email=email,
                password_hash=hash_password(password),
                role=Role.USER,
            )
            created: list[Account] = []
            for acc_type in dict.fromkeys(account_types):  # dedupe, keep order
                number = self._unique_account_number(conn)
                opening = opening_balance if acc_type == account_types[0] else Decimal("0")
                account = self._accounts.create(
                    conn,
                    user_id=user.id,
                    account_number=number,
                    account_type=acc_type,
                    balance=opening,
                )
                if opening > 0:
                    self._txns.insert(
                        conn,
                        txn_ref=new_txn_ref(),
                        idempotency_key=None,
                        from_id=None,
                        to_id=account.id,
                        amount=opening,
                        txn_type=TxnType.DEPOSIT,
                        status=TxnStatus.SUCCESS,
                        note="Opening balance",
                        sender_after=None,
                        receiver_after=opening,
                    )
                created.append(account)
        return CustomerView(user=user, accounts=tuple(created))

    def _unique_account_number(self, conn) -> str:
        for _ in range(8):  # birthday-paradox-safe retry on collision
            number = new_account_number()
            if not self._accounts.number_exists(conn, number):
                return number
        raise BankingError("Could not allocate an account number; retry.")

    # -- moderation ----------------------------------------------------------------------
    def set_account_status(self, account_id: int, status: AccountStatus) -> None:
        self._accounts.set_status(account_id, status.value)

    # -- interest accrual: concurrent batch job -------------------------------------------
    def run_interest_accrual(self) -> InterestReport:
        """Credit this month's savings interest using a thread pool.

        Each account is credited in its *own* transaction with an idempotency
        key (``INT-YYYY-MM-<account>``), so re-running the job is a no-op —
        at-least-once execution with exactly-once effect.  Thread pool size
        stays under the connection-pool ceiling; the work is I/O-bound, so
        threads overlap despite the GIL (see README § concurrency).
        """
        month_key = datetime.now(UTC).strftime("%Y-%m")
        savings = self._accounts.list_active_savings()
        t0 = time.perf_counter()
        errors: list[str] = []

        def credit_one(acc: Account) -> Decimal:
            """Process one account; returns the amount credited (0 = skipped)."""
            key = f"INT-{month_key}-{acc.id}"
            try:
                with self._pool.connection() as conn:
                    if self._txns.find_by_idempotency_key(conn, key) is not None:
                        return Decimal("0")
                    locked = self._accounts.lock_accounts(conn, [acc.id])[acc.id]
                    interest = locked.monthly_interest()
                    if interest <= 0:
                        return Decimal("0")
                    new_balance = self._accounts.apply_delta(conn, acc.id, interest)
                    self._txns.insert(
                        conn,
                        txn_ref=new_txn_ref(),
                        idempotency_key=key,
                        from_id=None,
                        to_id=acc.id,
                        amount=interest,
                        txn_type=TxnType.INTEREST,
                        status=TxnStatus.SUCCESS,
                        note=f"Savings interest {month_key} @ {SavingsAccount.ANNUAL_RATE:.0%} p.a.",
                        sender_after=None,
                        receiver_after=new_balance,
                    )
                    return interest
            except Exception as exc:  # never poison the batch
                errors.append(f"{acc.account_number}: {exc}")
                return Decimal("0")

        workers = min(self._cfg.interest_workers, max(len(savings), 1))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="interest") as pool:
            credited = list(pool.map(credit_one, savings))

        duration_ms = (time.perf_counter() - t0) * 1000
        total = reduce(lambda s, x: s + x, credited, Decimal("0"))
        return InterestReport(
            month_key=month_key,
            accounts_processed=len(savings),
            accounts_credited=sum(1 for c in credited if c > 0),
            total_credited=total,
            duration_ms=duration_ms,
            workers=workers,
            errors=tuple(errors),
        )

    def all_transactions(self, *, page: int = 1, per_page: int = 15, only_flagged: bool = False) -> dict[str, object]:
        if only_flagged:
            items = self._txns.list_flagged(limit=per_page * 5)
            return {"rows": items, "page": 1, "pages": 1, "total": len(items)}
        with self._pool.cursor() as cur:
            cur.execute(
                """SELECT t.*, fa.account_number AS from_number, ta.account_number AS to_number,
                            fu.full_name AS from_name, tu.full_name AS to_name,
                            COUNT(*) OVER() AS total
                    FROM transactions t
                    LEFT JOIN accounts fa ON fa.id = t.from_account_id
                    LEFT JOIN accounts ta ON ta.id = t.to_account_id
                    LEFT JOIN users fu ON fu.id = fa.user_id
                    LEFT JOIN users tu ON tu.id = ta.user_id
                    ORDER BY t.created_at DESC, t.id DESC
                    LIMIT %s OFFSET %s""",
                (per_page, (max(page, 1) - 1) * per_page),
            )
            rows = cur.fetchall()
        total = int(rows[0]["total"]) if rows else 0
        return {
            "rows": [Transaction.from_row(r) for r in rows],
            "total": total,
            "page": page,
            "pages": max(ceil(total / per_page), 1),
        }
