"""Web smoke tests: real Flask test-client against a real (test) PostgreSQL.

Covers routing, session auth guards, redirects and key HTML rendering —
the end-to-end layer of the testing pyramid. Requires TEST_DATABASE_URL.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    os.environ["DATABASE_URL"] = url

    from bank.db import ConnectionPool

    ConnectionPool.reset()  # make sure the app pools the TEST database
    from app import create_app

    app = create_app()
    app.config.update(TESTING=True)

    pool = ConnectionPool.instance()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE transactions, accounts, users RESTART IDENTITY CASCADE")
    from scripts.seed import seed

    seed(pool)

    yield app.test_client()

    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE transactions, accounts, users RESTART IDENTITY CASCADE")
    ConnectionPool.reset()
    os.environ.pop("DATABASE_URL", None)


def test_login_page_renders(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "Sign in securely" in r.get_data(as_text=True)


def test_pages_require_auth(client):
    assert client.get("/dashboard").status_code == 302
    assert client.get("/admin/dashboard").status_code == 302
    assert client.get("/api/balance").status_code == 302


def test_bad_login_rejected_and_throttled_shape(client):
    r = client.post("/login", data={"username": "aarav.sharma", "password": "WRONG"})
    assert r.status_code == 401


def test_user_journey(client):
    r = client.post("/login", data={"username": "aarav.sharma", "password": "User@123"})
    assert r.status_code == 302 and "/dashboard" in r.headers["Location"]

    dash = client.get("/dashboard")
    assert dash.status_code == 200
    body = dash.get_data(as_text=True)
    assert "Namaste, Aarav" in body and "transferModal" in body

    r = client.post("/api/validate-account", json={"account_number": "0000000000"})
    assert r.status_code == 200 and r.get_json()["found"] is False

    r = client.get("/transactions")
    assert r.status_code == 200

    logout = client.get("/logout")
    assert logout.status_code == 302
    assert client.get("/dashboard").status_code == 302  # session really cleared


def test_user_cannot_enter_admin_area(client):
    client.post("/login", data={"username": "aarav.sharma", "password": "User@123"})
    r = client.get("/admin/dashboard")
    assert r.status_code == 302  # bounced by role guard, never 200


def test_admin_journey(client):
    r = client.post("/admin/login", data={"username": "admin", "password": "Admin@123"})
    assert r.status_code == 302
    dash = client.get("/admin/dashboard")
    assert dash.status_code == 200
    assert "Command centre" in dash.get_data(as_text=True)
    assert client.get("/admin/customers").status_code == 200
    assert client.get("/admin/transactions").status_code == 200


def test_404_page(client):
    r = client.get("/no-such-page")
    assert r.status_code == 404
    assert "off the ledger" in r.get_data(as_text=True)
