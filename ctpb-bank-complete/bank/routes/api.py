"""JSON API consumed by the front-end widgets (transfer wizard, live balance,
account validation, note breakdown) — plus a health probe for containers."""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from ..db import get_pool, ping
from ..models import Role
from ..security import login_required
from ..services import BankingError
from ..utils import ist as fmt_ist
from ..utils import parse_amount
from . import get_banking

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _error(message: str, status: int):
    return jsonify(ok=False, error=message), status


@api_bp.get("/health")
def health():
    db_ok = ping(get_pool())
    return jsonify(ok=db_ok, db="up" if db_ok else "down"), 200 if db_ok else 503


@api_bp.post("/validate-account")
@login_required()
def validate_account():
    data = request.get_json(silent=True) or request.form
    v = get_banking().validate_account(str(data.get("account_number", "")))
    return jsonify(
        ok=True,
        found=v.found,
        usable=v.usable,
        number=v.account_number,
        holder=v.holder_name,
        account_type=v.account_type,
        status=v.status,
    )


@api_bp.get("/balance")
@login_required(Role.USER)
def balance():
    payload = get_banking().balance_payload(g.current_user)
    return jsonify(ok=True, **payload)


@api_bp.post("/transfer")
@login_required(Role.USER)
def transfer():
    data = request.get_json(silent=True) or request.form
    try:
        amount = parse_amount(str(data.get("amount", "")))
    except ValueError:
        return _error("Enter a valid amount, e.g. 1250.00", 400)
    try:
        from_id = int(data.get("from_account_id") or 0)
    except (TypeError, ValueError):
        from_id = 0
    try:
        result = get_banking().transfer(
            sender=g.current_user,
            from_account_id=from_id,
            to_account_number=str(data.get("to_account_number", "")),
            amount=amount,
            note=str(data.get("note", "")),
            idempotency_key=str(data.get("idempotency_key", "")),
        )
    except BankingError as exc:
        return _error(str(exc), 400)
    txn = result.transaction
    return jsonify(
        ok=True,
        ref=txn.txn_ref,
        amount=str(txn.amount),
        status=txn.status.value,
        flagged=bool(result.flag_reasons),
        reasons=list(result.flag_reasons),
        duplicate=result.duplicate,
        created=fmt_ist(txn.created_at),
    )


@api_bp.get("/denominations")
@login_required()
def denominations():
    try:
        amount = int(float(request.args.get("amount", "0") or 0))
    except (TypeError, ValueError):
        amount = 0
    if not 0 <= amount <= 10_000_000:
        return _error("Amount must be between 0 and ₹1,00,00,000.", 400)
    items = [{"note": note, "count": count} for note, count in get_banking().denominations(amount)]
    return jsonify(ok=True, amount=amount, items=items)
