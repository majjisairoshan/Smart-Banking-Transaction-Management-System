"""Application configuration (12-factor style).

Everything is resolved from environment variables with sensible local
defaults, so the same code runs against:

* a developer's own PostgreSQL ``CTPBD`` database (``DB_*`` vars),
* a single ``DATABASE_URL`` (containers / CI / this sandbox),
* docker-compose service discovery (``db`` host).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

try:  # loading .env is a convenience, never a requirement
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional
    pass


@dataclass(frozen=True)
class Config:
    """Immutable application settings."""

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "CTPBD"
    db_user: str = "postgres"
    db_password: str = "postgres"
    database_url: str | None = None

    secret_key: str = "ctpbd-dev-secret-change-me"
    session_lifetime: timedelta = timedelta(minutes=30)

    db_pool_min: int = 1
    db_pool_max: int = 10
    interest_workers: int = 4

    # Business-rule knobs (account invariants themselves live in bank.models)
    fraud_amount_threshold: Decimal = Decimal("100000.00")
    fraud_velocity_limit: int = 3
    fraud_velocity_window_seconds: int = 60
    max_transfer_amount: Decimal = Decimal("1000000.00")

    bank_name: str = "CTPB Bank"
    bank_ifsc: str = "CTPB0001234"

    @classmethod
    def from_env(cls) -> Config:
        def _int(key: str, default: int) -> int:
            try:
                return int(os.environ.get(key, default))
            except (TypeError, ValueError):
                return default

        return cls(
            db_host=os.environ.get("DB_HOST", "localhost"),
            db_port=_int("DB_PORT", 5432),
            db_name=os.environ.get("DB_NAME", "CTPBD"),
            db_user=os.environ.get("DB_USER", "postgres"),
            db_password=os.environ.get("DB_PASSWORD", "postgres"),
            database_url=os.environ.get("DATABASE_URL") or None,
            secret_key=os.environ.get("FLASK_SECRET_KEY", "ctpbd-dev-secret-change-me"),
            db_pool_max=_int("DB_POOL_MAX", 10),
            interest_workers=_int("INTEREST_WORKERS", 4),
        )

    @property
    def dsn(self) -> str:
        """PostgreSQL DSN. ``DATABASE_URL`` wins over individual parts."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def maintenance_dsn(self) -> str:
        """DSN to the cluster's maintenance DB — used by scripts to CREATE DATABASE CTPBD."""
        if self.database_url:
            base, _, tail = self.database_url.rpartition("/")
            dbname = tail.split("?", 1)[0]
            url = self.database_url.replace(f"/{dbname}", "/postgres", 1)
            return url
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/postgres"
        )
