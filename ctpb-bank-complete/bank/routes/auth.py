"""Authentication routes: customer login, admin login, logout.

Login attempts are throttled per (role, IP) with a sliding-window limiter
(5 tries / 5 minutes) — brute-force protection that also demonstrates an
O(1)-amortised deque-based rate limiter.
"""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.wrappers import Response

from ..models import Role
from ..security import LoginRateLimiter
from ..services import AuthenticationError
from . import get_auth

auth_bp = Blueprint("auth", __name__)
_limiter = LoginRateLimiter(max_attempts=5, window_seconds=300)


@auth_bp.route("/")
def index() -> Response:
    if session.get("role") == Role.ADMIN.value:
        return redirect(url_for("admin.dashboard"))
    if session.get("role") == Role.USER.value:
        return redirect(url_for("user.dashboard"))
    return redirect(url_for("auth.login"))


def _client_key(role: Role) -> str:
    ip = (request.headers.get("X-Forwarded-For", request.remote_addr or "?")).split(",")[0].strip()
    return f"{role.value}:{ip}"


def _handle_login(role: Role, template: str):
    if request.method == "POST":
        key = _client_key(role)
        if not _limiter.allow(key):
            flash("Too many attempts — please wait a few minutes and try again.", "error")
            return render_template(template), 429
        try:
            user = get_auth().authenticate(
                request.form.get("username", ""),
                request.form.get("password", ""),
                role=role,
            )
        except AuthenticationError as exc:
            flash(str(exc), "error")
            return render_template(template), 401

        _limiter.reset(key)
        session.clear()
        session.permanent = True
        session.update(user_id=user.id, role=user.role.value, name=user.full_name)
        nxt = request.args.get("next", "")
        if nxt.startswith("/") and not nxt.startswith("//"):
            return redirect(nxt)
        return redirect(url_for("admin.dashboard" if role is Role.ADMIN else "user.dashboard"))
    return render_template(template)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("role") == Role.USER.value:
        return redirect(url_for("user.dashboard"))
    return _handle_login(Role.USER, "login.html")


@auth_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("role") == Role.ADMIN.value:
        return redirect(url_for("admin.dashboard"))
    return _handle_login(Role.ADMIN, "admin_login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out securely.", "info")
    return redirect(url_for("auth.login"))
