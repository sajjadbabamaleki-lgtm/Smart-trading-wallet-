"""Comparing what a run reported writing with what the store holds."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.market_data.reconcile import Reconciliation

START = datetime(2026, 9, 15, 4, 22, tzinfo=UTC)
END = START + timedelta(minutes=20)


def result(reported: int, stored: int) -> Reconciliation:
    return Reconciliation(reported=reported, stored=stored, range_start=START, range_end=END)


def test_equal_counts_agree() -> None:
    assert result(6049, 6049).agrees
    assert result(6049, 6049).missing == 0


def test_a_short_store_is_a_mismatch() -> None:
    """The case this exists for: rows counted and never persisted."""
    outcome = result(6049, 4000)
    assert not outcome.agrees
    assert outcome.missing == 2049


def test_a_store_holding_more_is_also_a_mismatch() -> None:
    """Not clamped to zero — it is a different problem, not a clean run.

    More rows than this run wrote means the range caught someone else's: an
    overlapping recorder, or a window wider than the run. Reporting it as zero
    missing would hide a recorder writing over another's data.
    """
    outcome = result(100, 150)
    assert not outcome.agrees
    assert outcome.missing == -50


def test_the_range_travels_with_the_verdict() -> None:
    """A count without its window cannot be re-derived or disputed."""
    described = result(10, 10).as_dict()
    assert described["range_start"] == START.isoformat()
    assert described["range_end"] == END.isoformat()
    assert described["agrees"] is True
