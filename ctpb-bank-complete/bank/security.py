"""Authentication & request-guard helpers.

* Passwords: salted scrypt via Werkzeug (never stored in clear).
* Sessions: signed Flask cookies (HttpOnly, SameSite=Lax).
* ``LoginRateLimiter``: sliding-window throttle — O(1) amortised deque ops.
* ``login_required`` is a *decorator factory* (higher-order function).
"""
from __future__ import annotations

import functools
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any, TypeVar

from flask import flash, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .models import Role

F = TypeVar("F", bound=Callable[..., Any])


def hash_password(plain: str) -> str:
    return generate_password_hash(plain)


def verify_password(stored_hash: str, plain: str) -> bool:
    try:
        return check_password_hash(stored_hash, plain)
    except ValueError:  # corrupt hash format
        return False


class LoginRateLimiter:
    """Sliding-window limiter: at most ``max_attempts`` per ``window_seconds``.

    Abstraction: timestamps of attempts per key kept in a deque; expired
    entries are popped from the left, so ``allow()`` is amortised O(1).
    A lock makes it safe under Flask's threaded server.
    """

    def __init__(self, max_attempts: int = 5, window_seconds: float = 300.0) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self._window:
                hits.pop(0)
            if len(hits) >= self._max:
                return False
            hits.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


def login_required(role: Role | None = None) -> Callable[[F], F]:
    """Guard a view: must be logged in, and (optionally) hold ``role``."""

    def decorator(view: F) -> F:
        @functools.wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if "user_id" not in session:
                flash("Please sign in to continue.", "info")
                target = url_for("auth.admin_login") if role is Role.ADMIN else url_for("auth.login")
                return redirect(f"{target}?next={request.path}")
            if role is not None and session.get("role") != role.value:
                flash("You are not authorised for that area.", "error")
                return redirect(url_for("auth.index"))
            return view(*args, **kwargs)

        return wrapped  # type: ignore[return-value]

    return decorator
