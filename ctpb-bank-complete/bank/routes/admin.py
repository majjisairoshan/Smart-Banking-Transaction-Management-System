"""Admin console pages: overview stats, customers, ledger, interest job."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from psycopg2 import IntegrityError
from psycopg2.errors import UniqueViolation

from ..models import AccountStatus, Role
from ..security import login_required
from ..services import BankingError
from ..utils import inr, parse_amount
from . import get_admin

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _page_arg() -> int:
    try:
        return max(int(request.args.get("page", 1)), 1)
    except (TypeError, ValueError):
        return 1


@admin_bp.route("/dashboard")
@login_required(Role.ADMIN)
def dashboard():
    return render_template("admin/dashboard.html", s=get_admin().stats())


@admin_bp.route("/customers")
@login_required(Role.ADMIN)
def customers():
    search = request.args.get("q", "").strip()
    data = get_admin().customers(search=search, page=_page_arg())
    return render_template("admin/customers.html", d=data, q=search)


@admin_bp.route("/customers/new", methods=["POST"])
@login_required(Role.ADMIN)
def customer_new():
    try:
        opening = parse_amount(request.form.get("opening_balance", "0") or "0")
        view = get_admin().create_customer(
            full_name=request.form.get("full_name", ""),
            username=request.form.get("username", ""),
            email=request.form.get("email", ""),
            password=request.form.get("password", ""),
            account_types=request.form.getlist("account_types"),
            opening_balance=opening,
        )
    except (BankingError, ValueError) as exc:
        flash(str(exc), "error")
    except IntegrityError as exc:
        msg = "Username or email already exists." if isinstance(exc.orig, UniqueViolation) else "Database constraint violated."
        flash(msg, "error")
    else:
        numbers = ", ".join(f"{a.account_type.value} {a.account_number}" for a in view.accounts)
        flash(f"Customer {view.user.full_name} created — {numbers}.", "success")
    return redirect(url_for("admin.customers"))


@admin_bp.route("/accounts/<int:account_id>/status", methods=["POST"])
@login_required(Role.ADMIN)
def account_status(account_id: int):
    raw = request.form.get("status", "")
    if raw not in (AccountStatus.ACTIVE.value, AccountStatus.FROZEN.value):
        flash("Invalid status.", "error")
    else:
        get_admin().set_account_status(account_id, AccountStatus(raw))
        verb = "unfrozen" if raw == "active" else "frozen"
        flash(f"Account #{account_id} {verb}.", "success")
    return redirect(request.referrer or url_for("admin.customers"))


@admin_bp.route("/interest/run", methods=["POST"])
@login_required(Role.ADMIN)
def interest_run():
    report = get_admin().run_interest_accrual()
    flash(
        f"Interest {report.month_key}: credited {inr(report.total_credited)} to "
        f"{report.accounts_credited}/{report.accounts_processed} savings accounts in "
        f"{report.duration_ms:.0f} ms using {report.workers} worker threads"
        + (f" ({len(report.errors)} errors)" if report.errors else "")
        + " — re-running is safe (idempotent).",
        "success",
    )
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/transactions")
@login_required(Role.ADMIN)
def transactions():
    only_flagged = request.args.get("flagged", "") == "1"
    data = get_admin().all_transactions(page=_page_arg(), only_flagged=only_flagged)
    return render_template("admin/transactions.html", d=data, flagged=only_flagged)
