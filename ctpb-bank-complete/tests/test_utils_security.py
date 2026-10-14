"""Formatting helpers, amount parsing, rate limiter and password hashing."""
from __future__ import annotations

from decimal import Decimal

import pytest

from bank.security import LoginRateLimiter, hash_password, verify_password
from bank.utils import (
    initials,
    inr,
    mask_account,
    new_account_number,
    normalize_account_number,
    parse_amount,
    sparkline_points,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (Decimal("0"), "₹0.00"),
        (Decimal("999"), "₹999.00"),
        (Decimal("1000"), "₹1,000.00"),
        (Decimal("123456.50"), "₹1,23,456.50"),
        (Decimal("12345678.90"), "₹1,23,45,678.90"),
        (Decimal("-1000"), "-₹1,000.00"),
    ],
)
def test_inr_indian_grouping(value, expected):
    assert inr(value) == expected


class TestParseAmount:
    def test_common_shapes(self):
        assert parse_amount("12,500.50") == Decimal("12500.50")
        assert parse_amount("₹100") == Decimal("100.00")
        assert parse_amount("  42 ") == Decimal("42.00")

    @pytest.mark.parametrize("bad", ["", "abc", "10.999", "1.2.3", "--5", "1e4"])
    def test_rejection(self, bad):
        with pytest.raises(ValueError):
            parse_amount(bad)

    def test_sloppy_grouping_is_tolerated(self):
        # commas are formatting noise — '1,00,0' means 1000 to the parser
        assert parse_amount("1,00,0") == Decimal("1000.00")


def test_account_number_normalisation():
    assert normalize_account_number("5010 234 821") == "5010234821"
    assert normalize_account_number("50-10-23-48-21") == "5010234821"
    assert normalize_account_number(None) == ""


def test_mask_and_initials():
    assert mask_account("5010234821") == "···· 4821"
    assert initials("Aarav Sharma") == "AS"
    assert initials("meera") == "M"
    assert initials("") == "?"


def test_account_number_generator_shape():
    numbers = {new_account_number() for _ in range(50)}
    assert all(len(n) == 10 and n.isdigit() and n.startswith("50") for n in numbers)
    assert len(numbers) > 40  # effectively unique


def test_sparkline_points():
    pts = sparkline_points([1, 3, 2, 5], width=100, height=20)
    coords = [tuple(map(float, p.split(","))) for p in pts.split(" ")]
    assert len(coords) == 4
    assert coords[0][1] > coords[3][1]  # higher value → smaller SVG y


class TestRateLimiter:
    def test_allows_then_blocks_then_resets(self):
        rl = LoginRateLimiter(max_attempts=3, window_seconds=60)
        assert rl.allow("ip1") and rl.allow("ip1") and rl.allow("ip1")
        assert not rl.allow("ip1")
        assert rl.allow("ip2")          # independent keys
        rl.reset("ip1")
        assert rl.allow("ip1")


class TestPasswords:
    def test_roundtrip(self):
        h = hash_password("Sup3rSecret!")
        assert h != "Sup3rSecret!"
        assert verify_password(h, "Sup3rSecret!")
        assert not verify_password(h, "wrong")

    def test_corrupt_hash_fails_safely(self):
        assert not verify_password("not-a-real-hash", "anything")
