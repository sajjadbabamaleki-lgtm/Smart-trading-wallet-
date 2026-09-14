"""Session capture and reload."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from services.market_data.capture import (
    SYNTHETIC_FALLBACK_BASE,
    CaptureError,
    CaptureHeader,
    SessionWriter,
    load_session,
)
from services.market_data.sinks import RawFrame

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/hyperliquid"
NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)


def header() -> CaptureHeader:
    return CaptureHeader(
        format_version=1,
        venue="hyperliquid",
        source="hyperliquid_ws",
        assets=("BTC",),
        channels=("trades",),
        started_at=NOW.isoformat(),
    )


def frame(index: int, *, at: datetime | None = None) -> RawFrame:
    moment = at or (NOW + timedelta(milliseconds=index))
    return RawFrame(
        raw_id=f"raw_{index}",
        source="hyperliquid_ws",
        venue="hyperliquid",
        channel="trades",
        payload=json.dumps(
            {
                "channel": "trades",
                "data": [
                    {
                        "coin": "BTC",
                        "side": "B",
                        "px": "60000",
                        "sz": "0.01",
                        "time": int(moment.timestamp() * 1000),
                        "tid": 7000 + index,
                    }
                ],
            },
            separators=(",", ":"),
        ),
        received_at_iso=moment.isoformat(),
        received_monotonic_ns=index * 1_000_000,
    )


class TestRoundTrip:
    def test_a_written_session_reloads_with_its_receipts(self, tmp_path: Path) -> None:
        path = tmp_path / "session.jsonl"
        with SessionWriter(path, header()) as writer:
            for index in range(3):
                writer.write(frame(index))
            assert writer.frames_written == 3

        session = load_session(path)
        assert len(session.frames) == 3
        assert not session.synthetic_receipts
        assert session.frames[0].receipt.local_receive_time == NOW
        assert session.frames[2].receipt.local_receive_monotonic_ns == 2_000_000

    def test_the_header_survives_the_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "session.jsonl"
        with SessionWriter(path, header()) as writer:
            writer.write(frame(0))

        loaded = load_session(path).header
        assert loaded is not None
        assert loaded.venue == "hyperliquid"
        assert loaded.assets == ("BTC",)
        assert loaded.format_version == 1

    def test_payloads_are_preserved_byte_for_byte(self, tmp_path: Path) -> None:
        path = tmp_path / "session.jsonl"
        original = frame(0)
        with SessionWriter(path, header()) as writer:
            writer.write(original)

        replayed = load_session(path).frames[0]
        assert json.loads(replayed.payload) == json.loads(original.payload)

    def test_frames_are_flushed_as_written(self, tmp_path: Path) -> None:
        """A capture interrupted by a crash must still be replayable."""
        path = tmp_path / "session.jsonl"
        with SessionWriter(path, header()) as writer:
            writer.write(frame(0))
            # Readable before the writer closes.
            assert len(load_session(path).frames) == 1
            writer.write(frame(1))

    def test_using_the_writer_outside_its_context_is_refused(self, tmp_path: Path) -> None:
        writer = SessionWriter(tmp_path / "session.jsonl", header())
        with pytest.raises(CaptureError, match="outside its context"):
            writer.write(frame(0))


class TestSyntheticReceipts:
    def test_bare_frames_get_receipts_derived_from_venue_time(self) -> None:
        session = load_session(FIXTURES / "btc_sequence_gap.jsonl")
        assert session.synthetic_receipts
        first = session.frames[0].receipt
        assert first.exchange_time is None  # not set until normalization
        # 1789387199900ms + 1ms of synthetic delay.
        assert first.local_receive_time == datetime.fromtimestamp(1789387199.901, tz=UTC)

    def test_a_synthetic_session_is_flagged(self) -> None:
        """So a latency analysis can refuse it rather than fabricate a number."""
        assert load_session(FIXTURES / "btc_session.jsonl").synthetic_receipts
        assert not load_session(FIXTURES / "btc_capture.jsonl").synthetic_receipts

    def test_receipts_never_move_backwards(self) -> None:
        """ReplayClock refuses a backwards step, so the loader must not emit one."""
        for name in (
            "btc_session.jsonl",
            "btc_malformed.jsonl",
            "btc_duplicates.jsonl",
            "btc_sequence_gap.jsonl",
            "btc_capture.jsonl",
        ):
            times = [
                frame.receipt.local_receive_time for frame in load_session(FIXTURES / name).frames
            ]
            assert times == sorted(times), f"{name} has out-of-order receipts"

    def test_leading_timeless_frames_are_anchored_to_the_session(self) -> None:
        """Otherwise the reported duration is decades, in an evidence artifact."""
        session = load_session(FIXTURES / "btc_session.jsonl")
        assert session.duration_seconds < 1.0
        assert session.frames[0].receipt.local_receive_time > SYNTHETIC_FALLBACK_BASE

    def test_a_wholly_timeless_file_falls_back_without_error(self, tmp_path: Path) -> None:
        path = tmp_path / "control_only.jsonl"
        path.write_text('{"channel":"pong"}\n{"channel":"pong"}\n', encoding="utf-8")
        session = load_session(path)
        assert len(session.frames) == 2
        assert session.frames[0].receipt.local_receive_time == SYNTHETIC_FALLBACK_BASE
        assert session.duration_seconds == pytest.approx(0.001)


class TestLoaderRobustness:
    def test_a_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(CaptureError, match="does not exist"):
            load_session(tmp_path / "absent.jsonl")

    def test_a_malformed_line_is_reported_not_fatal(self, tmp_path: Path) -> None:
        """One bad line must not make the whole session unreplayable."""
        path = tmp_path / "session.jsonl"
        path.write_text('{"channel":"pong"}\nnot json\n{"channel":"pong"}\n', encoding="utf-8")
        session = load_session(path)
        assert session.malformed_lines == (2,)
        assert len(session.frames) == 2

    def test_a_header_after_the_first_line_is_a_format_error(self, tmp_path: Path) -> None:
        path = tmp_path / "session.jsonl"
        path.write_text('{"channel":"pong"}\n' + header().to_json() + "\n", encoding="utf-8")
        with pytest.raises(CaptureError, match="must be the first line"):
            load_session(path)

    def test_comments_and_blank_lines_are_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "session.jsonl"
        path.write_text('// a note\n\n{"channel":"pong"}\n', encoding="utf-8")
        assert len(load_session(path).frames) == 1

    def test_an_envelope_without_a_receipt_time_is_malformed(self, tmp_path: Path) -> None:
        """The envelope exists to carry it; one without it is a broken capture."""
        path = tmp_path / "session.jsonl"
        path.write_text('{"frame":{"channel":"pong"}}\n', encoding="utf-8")
        session = load_session(path)
        assert session.malformed_lines == (1,)
        assert session.frames == ()

    def test_a_naive_receipt_time_is_treated_as_utc(self, tmp_path: Path) -> None:
        path = tmp_path / "session.jsonl"
        path.write_text(
            '{"received_at":"2026-09-14T12:00:00","frame":{"channel":"pong"}}\n',
            encoding="utf-8",
        )
        moment = load_session(path).frames[0].receipt.local_receive_time
        assert moment.tzinfo is not None
        assert moment == NOW
