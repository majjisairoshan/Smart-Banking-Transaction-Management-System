"""Domain model — the object-oriented heart of the system (rubric §3).

* ``Account`` is an **abstract base class**; ``SavingsAccount`` and
  ``CurrentAccount`` implement the account-specific invariants
  (polymorphism: a transfer never cares which type it is talking to).
* ``account_from_row`` is a small **Factory** that reconstitutes the right
  subtype from a database row.
* Money is always ``Decimal`` — never binary floats.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any, ClassVar

CENT = Decimal("0.01")


def money_round(value: Decimal) -> Decimal:
    """Round to paise using bank-acceptable half-up rounding."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------
# Enumerations — a single source of truth shared by code and DB CHECK constraints
# --------------------------------------------------------------------------
class Role(StrEnum):
    USER = "user"
    ADMIN = "admin"


class AccountType(StrEnum):
    SAVINGS = "savings"
    CURRENT = "current"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    FROZEN = "frozen"


class TxnType(StrEnum):
    TRANSFER = "transfer"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    INTEREST = "interest"


class TxnStatus(StrEnum):
    SUCCESS = "success"
    FLAGGED = "flagged"
    FAILED = "failed"


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class User:
    id: int
    username: str
    full_name: str
    email: str
    password_hash: str
    role: Role
    created_at: datetime

    @classmethod
    def from_row(cls, row: Any) -> User:
        return cls(
            id=row["id"],
            username=row["username"],
            full_name=row["full_name"],
            email=row["email"],
            password_hash=row["password_hash"],
            role=Role(row["role"]),
            created_at=row["created_at"],
        )


# --------------------------------------------------------------------------
# Accounts — abstract base + concrete subtypes (inheritance & polymorphism)
# --------------------------------------------------------------------------
@dataclass
class Account(ABC):
    """Abstract bank account. Subclasses define the debit floor and yield."""

    id: int
    account_number: str
    user_id: int
    balance: Decimal
    status: AccountStatus
    created_at: datetime
    holder_name: str = field(default="", compare=False)

    account_type: ClassVar[AccountType]

    # -- polymorphic rules --------------------------------------------------
    @abstractmethod
    def withdrawal_floor(self) -> Decimal:
        """Lowest balance this account type is allowed to reach."""

    @abstractmethod
    def annual_interest_rate(self) -> Decimal:
        """Annual interest rate as a fraction (0.04 = 4%)."""

    # -- shared behaviour -----------------------------------------------------
    def can_debit(self, amount: Decimal) -> bool:
        """Invariant: active, and the post-debit balance stays above the floor."""
        return (
            self.status is AccountStatus.ACTIVE
            and (self.balance - amount) >= self.withdrawal_floor()
        )

    def can_credit(self) -> bool:
        return self.status is AccountStatus.ACTIVE

    def monthly_interest(self) -> Decimal:
        """Interest for one month on the current balance (simple rule, rounded)."""
        return money_round(self.balance * self.annual_interest_rate() / Decimal(12))

    def is_active(self) -> bool:
        return self.status is AccountStatus.ACTIVE


class SavingsAccount(Account):
    """Savings: must keep a minimum balance; earns interest."""

    account_type: ClassVar[AccountType] = AccountType.SAVINGS
    MIN_BALANCE: ClassVar[Decimal] = Decimal("1000.00")
    ANNUAL_RATE: ClassVar[Decimal] = Decimal("0.04")

    def withdrawal_floor(self) -> Decimal:
        return self.MIN_BALANCE

    def annual_interest_rate(self) -> Decimal:
        return self.ANNUAL_RATE


class CurrentAccount(Account):
    """Current: no interest, but an overdraft cushion for businesses."""

    account_type: ClassVar[AccountType] = AccountType.CURRENT
    OVERDRAFT_LIMIT: ClassVar[Decimal] = Decimal("50000.00")

    def withdrawal_floor(self) -> Decimal:
        return -self.OVERDRAFT_LIMIT

    def annual_interest_rate(self) -> Decimal:
        return Decimal("0")


_ACCOUNT_SUBTYPES: dict[AccountType, type[Account]] = {
    AccountType.SAVINGS: SavingsAccount,
    AccountType.CURRENT: CurrentAccount,
}


def account_from_row(row: Any) -> Account:
    """Factory: rebuild the correct Account subtype from a SQL row."""
    acc_type = AccountType(row["account_type"])
    return _ACCOUNT_SUBTYPES[acc_type](
        id=row["id"],
        account_number=row["account_number"],
        user_id=row["user_id"],
        balance=Decimal(str(row["balance"])),
        status=AccountStatus(row["status"]),
        created_at=row["created_at"],
        holder_name=row.get("holder_name") or "",
    )


# --------------------------------------------------------------------------
# Transactions
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Transaction:
    id: int
    txn_ref: str
    amount: Decimal
    txn_type: TxnType
    status: TxnStatus
    created_at: datetime
    note: str | None = None
    from_account_id: int | None = None
    to_account_id: int | None = None
    idempotency_key: str | None = None
    sender_balance_after: Decimal | None = None
    receiver_balance_after: Decimal | None = None
    # JOIN-decorated display fields
    from_number: str = ""
    to_number: str = ""
    from_name: str = ""
    to_name: str = ""

    @classmethod
    def from_row(cls, row: Any) -> Transaction:
        return cls(
            id=row["id"],
            txn_ref=row["txn_ref"],
            amount=Decimal(str(row["amount"])),
            txn_type=TxnType(row["txn_type"]),
            status=TxnStatus(row["status"]),
            created_at=row["created_at"],
            note=row.get("note"),
            from_account_id=row.get("from_account_id"),
            to_account_id=row.get("to_account_id"),
            idempotency_key=row.get("idempotency_key"),
            sender_balance_after=(
                Decimal(str(row["sender_balance_after"]))
                if row.get("sender_balance_after") is not None
                else None
            ),
            receiver_balance_after=(
                Decimal(str(row["receiver_balance_after"]))
                if row.get("receiver_balance_after") is not None
                else None
            ),
            from_number=row.get("from_number") or "",
            to_number=row.get("to_number") or "",
            from_name=row.get("from_name") or "",
            to_name=row.get("to_name") or "",
        )

    def direction_for(self, account_ids: set[int]) -> str:
        """'credit' | 'debit' | 'self' from the perspective of given accounts."""
        credited = self.to_account_id in account_ids
        debited = self.from_account_id in account_ids
        if credited and debited:
            return "self"
        return "credit" if credited else "debit"

    def counterparty_for(self, account_ids: set[int]) -> str:
        direction = self.direction_for(account_ids)
        if direction == "self":
            return "Own accounts"
        if direction == "credit":
            return self.from_name or self.from_number or "External"
        return self.to_name or self.to_number or "External"


# --------------------------------------------------------------------------
# Small immutable DTOs crossing the service → route/template boundary
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class AccountValidation:
    found: bool
    account_number: str
    holder_name: str = ""
    account_type: str = ""
    status: str = ""

    @property
    def usable(self) -> bool:
        return self.found and self.status == AccountStatus.ACTIVE.value


@dataclass(frozen=True)
class CustomerView:
    user: User
    accounts: tuple[Account, ...]

    @property
    def total_balance(self) -> Decimal:
        # functional fold over the account collection
        from functools import reduce

        return reduce(lambda acc, a: acc + a.balance, self.accounts, Decimal("0"))
