"""Customer-facing pages: dashboard, transactions, profile."""
from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from ..models import Role
from ..security import login_required
from ..services import BankingError
from . import get_banking

user_bp = Blueprint("user", __name__)

_TXN_TYPES = {"", "transfer", "deposit", "withdrawal", "interest"}
_SORTS = {"date_asc", "date_desc", "amount_asc", "amount_desc"}


def _int_arg(name: str, default: int) -> int:
    try:
        return max(int(request.args.get(name, default)), 1)
    except (TypeError, ValueError):
        return default


@user_bp.route("/dashboard")
@login_required(Role.USER)
def dashboard():
    overview = get_banking().overview(g.current_user)
    return render_template("dashboard.html", ov=overview)


@user_bp.route("/transactions")
@login_required(Role.USER)
def transactions():
    txn_type = request.args.get("type", "")
    if txn_type not in _TXN_TYPES:
        txn_type = ""
    sort = request.args.get("sort", "date_desc")
    if sort not in _SORTS:
        sort = "date_desc"
    hist = get_banking().history(
        g.current_user,
        page=_int_arg("page", 1),
        txn_type=txn_type or None,
        sort=sort,
    )
    return render_template("transactions.html", h=hist, txn_type=txn_type, sort=sort)


@user_bp.route("/profile", methods=["GET", "POST"])
@login_required(Role.USER)
def profile():
    svc = get_banking()
    if request.method == "POST":
        action = request.form.get("action", "")
        try:
            if action == "email":
                svc.update_email(g.current_user, request.form.get("email", ""))
                flash("Email address updated.", "success")
            elif action == "password":
                svc.change_password(
                    g.current_user,
                    request.form.get("old_password", ""),
                    request.form.get("new_password", ""),
                )
                flash("Password changed successfully.", "success")
            else:
                flash("Unknown action.", "error")
        except BankingError as exc:
            flash(str(exc), "error")
        return redirect(url_for("user.profile"))
    fresh = svc.accounts_of(g.current_user.id)
    return render_template("profile.html", accounts=fresh)
