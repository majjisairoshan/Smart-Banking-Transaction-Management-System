"""Unit tests for the hand-rolled algorithms."""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from bank.algorithms import (
    assess_transfer_risk,
    binary_search,
    greedy_denominations,
    merge_sort,
    sliding_window_count,
    top_k,
)

UTC = UTC
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


class TestMergeSort:
    def test_matches_builtin_on_random_data(self):
        rng = random.Random(7)
        data = [rng.randint(-500, 500) for _ in range(300)]
        assert merge_sort(data, key=lambda x: x) == sorted(data)

    def test_reverse(self):
        assert merge_sort([3, 1, 2], key=lambda x: x, reverse=True) == [3, 2, 1]

    def test_stability(self):
        pairs = [("a", 1), ("b", 0), ("c", 1), ("d", 0)]
        out = merge_sort(pairs, key=lambda p: p[1])
        assert [p[0] for p in out] == ["b", "d", "a", "c"]  # ties keep original order

    def test_edge_cases(self):
        assert merge_sort([], key=lambda x: x) == []
        assert merge_sort([42], key=lambda x: x) == [42]


class TestBinarySearch:
    ITEMS = sorted(random.Random(3).sample(range(1000), 200))

    def test_finds_extremes_and_middle(self):
        for target in (self.ITEMS[0], self.ITEMS[100], self.ITEMS[-1]):
            idx = binary_search(self.ITEMS, target, key=lambda x: x)
            assert self.ITEMS[idx] == target

    def test_missing_returns_minus_one(self):
        assert binary_search(self.ITEMS, -7, key=lambda x: x) == -1
        assert binary_search([], 5, key=lambda x: x) == -1


class TestGreedyDenominations:
    def test_textbook_breakdown(self):
        assert greedy_denominations(2876) == [(2000, 1), (500, 1), (200, 1), (100, 1), (50, 1), (20, 1), (5, 1), (1, 1)]

    def test_zero_and_exact_note(self):
        assert greedy_denominations(0) == []
        assert greedy_denominations(500) == [(500, 1)]

    def test_negative_rejected(self):
        with pytest.raises(ValueError):
            greedy_denominations(-5)

    def test_reconstruction_for_many_amounts(self):
        for amount in range(0, 5001, 137):
            assert sum(note * count for note, count in greedy_denominations(amount)) == amount


class TestRiskEngine:
    WINDOW = timedelta(seconds=60)

    def _times(self, *offsets_seconds):
        return [NOW - timedelta(seconds=s) for s in offsets_seconds]

    def test_clean_transfer(self):
        reasons = assess_transfer_risk(
            amount=Decimal("99999.99"), recent_outbound_desc=self._times(5000),
            now=NOW, window=self.WINDOW, velocity_limit=3, amount_threshold=Decimal("100000"),
        )
        assert reasons == ()

    def test_amount_threshold(self):
        reasons = assess_transfer_risk(
            amount=Decimal("100000"), recent_outbound_desc=(),
            now=NOW, window=self.WINDOW, velocity_limit=3, amount_threshold=Decimal("100000"),
        )
        assert len(reasons) == 1 and "amount" in reasons[0]

    def test_velocity_flag_and_early_exit(self):
        # 3 inside the window + older ones that must be ignored (early exit path)
        reasons = assess_transfer_risk(
            amount=Decimal("10"), recent_outbound_desc=self._times(5, 20, 59, 500, 800),
            now=NOW, window=self.WINDOW, velocity_limit=3, amount_threshold=Decimal("100000"),
        )
        assert len(reasons) == 1 and "4 transfers" in reasons[0]

    def test_sliding_window_counts_boundaries(self):
        times = self._times(0, 59.9 if False else 59, 60, 61)  # 60s is *inside* [now-60, now]
        assert sliding_window_count(times, NOW, self.WINDOW) == 3  # 0, 59, 60


class TestTopK:
    def test_returns_k_largest_in_order(self):
        assert top_k([5, 1, 9, 3, 7], 2, key=lambda x: x) == [9, 7]
        assert top_k([], 3, key=lambda x: x) == []
