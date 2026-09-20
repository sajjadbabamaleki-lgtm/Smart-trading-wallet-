"""Outside information: sentiment with history, headlines without.

Two tests carry the weight. The sentiment cut must be on our own availability
rather than the source's timestamp, so a backtest cannot read the afternoon's
sentiment at breakfast. And a headline's three timestamps must stay distinct,
because an outlet's claimed publication time can be earlier than the moment the
item actually appeared — and a backtest that trusted it would be reading the
news before it was news.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from libs.information.fear_greed import (
    EXTREME_FEAR,
    EXTREME_GREED,
    PUBLICATION_LAG,
    Reading,
    SentimentError,
    SentimentHistory,
    fetch_history,
    parse_reading,
)
from libs.information.headlines import (
    FeedError,
    Headline,
    deduplicate,
    fetch_feed,
    parse_feed,
)
from services.strategy_engine.decisions import Decision, SentimentExtreme
from tests.unit.test_candle_backtest import _with_sentiment

DAY = timedelta(days=1)
START = datetime(2026, 9, 1, tzinfo=UTC)


def reading(day: int, *, value: str) -> Reading:
    return Reading(moment=START + DAY * day, value=Decimal(value), classification="Fear")


def history(values: list[str]) -> SentimentHistory:
    return SentimentHistory.build(
        [reading(index, value=value) for index, value in enumerate(values)]
    )


class TestReading:
    def test_a_reading_is_usable_only_after_its_day(self) -> None:
        """The lag is conservative: the index describes a window ending
        somewhere inside its own day and the API does not say where."""
        assert reading(0, value="50").known_from == START + PUBLICATION_LAG

    def test_the_bands_are_the_publisher_s_own(self) -> None:
        assert reading(0, value=str(EXTREME_FEAR - 1)).is_extreme_fear
        assert reading(0, value=str(EXTREME_GREED)).is_extreme_greed
        assert not reading(0, value="50").is_extreme_fear
        assert not reading(0, value="50").is_extreme_greed


class TestParsing:
    def test_a_value_outside_the_scale_is_refused(self) -> None:
        with pytest.raises(SentimentError, match=r"outside 0\.\.100"):
            parse_reading({"value": "140", "timestamp": "1700000000"})

    def test_a_missing_field_is_refused(self) -> None:
        with pytest.raises(SentimentError, match="missing 'timestamp'"):
            parse_reading({"value": "50"})

    def test_a_reading_is_exact_not_a_float(self) -> None:
        parsed = parse_reading({"value": "37", "timestamp": "1700000000"})
        assert parsed.value == Decimal(37)


class TestPointInTime:
    def test_the_cut_is_on_our_availability_not_the_source_s_timestamp(self) -> None:
        """The leak this module is written to prevent.

        A reading stamped today is not usable today. Asked at its own
        timestamp, the history must return the *previous* reading — the one
        whose day had finished.
        """
        series = history(["10", "90"])
        asked = START + DAY
        held = series.at(asked)
        assert held is not None
        assert held.value == Decimal(10)

    def test_before_the_first_reading_is_known_there_is_nothing(self) -> None:
        assert history(["50"]).at(START) is None

    def test_the_latest_knowable_reading_is_returned(self) -> None:
        """Readings are stamped on days 0-3; each is knowable the day after.

        Asked on day 3, the knowable set is days 0, 1 and 2 — so the answer is
        the day-2 reading, 30, and the day-3 reading stamped that same morning
        is not yet available.
        """
        series = history(["10", "20", "30", "40"])
        held = series.at(START + DAY * 3)
        assert held is not None
        assert held.value == Decimal(30)

    def test_a_reading_is_unchanged_by_later_ones(self) -> None:
        """The property a backtest depends on."""
        values = ["10", "20", "30", "40", "50"]
        asked = START + DAY * 3
        full = history(values).at(asked)
        truncated = history(values[:3]).at(asked)
        assert full is not None and truncated is not None
        assert full.value == truncated.value

    def test_an_unsorted_history_is_refused(self) -> None:
        with pytest.raises(SentimentError, match="not in order"):
            SentimentHistory(
                moments=(START + DAY, START),
                readings=(reading(1, value="1"), reading(0, value="2")),
            )

    def test_an_empty_history_is_refused(self) -> None:
        with pytest.raises(SentimentError, match="no readings"):
            SentimentHistory.build([])


class TestFetching:
    def test_the_whole_history_comes_back_oldest_first(self) -> None:
        payload = {
            "data": [
                {"value": "30", "timestamp": "1700086400", "value_classification": "Fear"},
                {"value": "70", "timestamp": "1700000000", "value_classification": "Greed"},
            ]
        }

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        async def run() -> tuple[Reading, ...]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await fetch_history(client=client)

        readings = asyncio.run(run())
        assert [entry.value for entry in readings] == [Decimal(70), Decimal(30)]

    def test_a_payload_without_data_is_refused(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"metadata": {"error": None}})

        async def run() -> tuple[Reading, ...]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await fetch_history(client=client)

        with pytest.raises(SentimentError, match=r"\'data\' list"):
            asyncio.run(run())


FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Bitcoin   crosses
    a level</title>
    <link>https://example.com/one</link>
    <pubDate>Sat, 19 Sep 2026 12:00:00 GMT</pubDate>
  </item>
  <item>
    <title>No date here</title>
    <link>https://example.com/two</link>
  </item>
  <item>
    <title>Missing a link</title>
  </item>
</channel></rss>
"""

FETCHED = datetime(2026, 9, 19, 14, 0, tzinfo=UTC)


class TestFeedParsing:
    def test_items_without_a_title_or_link_are_skipped_not_raised_on(self) -> None:
        """One malformed entry must not discard the other forty."""
        items = parse_feed(FEED, source="example", fetched_at=FETCHED)
        assert len(items) == 2
        assert [item.link for item in items] == [
            "https://example.com/one",
            "https://example.com/two",
        ]

    def test_whitespace_inside_a_title_is_collapsed(self) -> None:
        """Otherwise two identical headlines differing only in spacing are two
        stories."""
        items = parse_feed(FEED, source="example", fetched_at=FETCHED)
        assert items[0].title == "Bitcoin crosses a level"

    def test_a_missing_publication_time_stays_missing(self) -> None:
        """A guess would erase the distinction these columns exist to keep."""
        items = parse_feed(FEED, source="example", fetched_at=FETCHED)
        assert items[1].published_at is None
        assert items[1].claimed_lag_seconds is None

    def test_the_claimed_lag_is_measured(self) -> None:
        """A feed that publishes hours late is one whose times cannot be trusted."""
        items = parse_feed(FEED, source="example", fetched_at=FETCHED)
        assert items[0].claimed_lag_seconds == 7200

    def test_our_receipt_time_is_always_present(self) -> None:
        for item in parse_feed(FEED, source="example", fetched_at=FETCHED):
            assert item.fetched_at == FETCHED

    def test_unparsable_xml_is_refused(self) -> None:
        with pytest.raises(FeedError, match="parsable XML"):
            parse_feed("<rss><channel", source="example", fetched_at=FETCHED)

    def test_an_unknown_source_names_the_known_ones(self) -> None:
        async def run() -> tuple[Headline, ...]:
            return await fetch_feed("nowhere")

        with pytest.raises(FeedError, match="known:"):
            asyncio.run(run())


class TestDeduplication:
    def _item(self, link: str, *, at: datetime) -> Headline:
        return Headline(source="example", title="t", link=link, published_at=None, fetched_at=at)

    def test_the_same_link_twice_is_one_story(self) -> None:
        items = [
            self._item("https://example.com/a", at=FETCHED),
            self._item("https://example.com/a", at=FETCHED + timedelta(hours=4)),
        ]
        assert len(deduplicate(items)) == 1

    def test_the_earliest_fetch_is_kept(self) -> None:
        """That is when we first knew; a re-fetch is not new information."""
        early = self._item("https://example.com/a", at=FETCHED)
        late = self._item("https://example.com/a", at=FETCHED + timedelta(hours=4))
        assert deduplicate([late, early])[0].fetched_at == FETCHED

    def test_different_links_are_different_stories(self) -> None:
        items = [
            self._item("https://example.com/a", at=FETCHED),
            self._item("https://example.com/b", at=FETCHED),
        ]
        assert len(deduplicate(items)) == 2

    def test_the_identity_is_stable_across_a_headline_edit(self) -> None:
        """An outlet that rewrites a headline has not published a new story."""
        first = Headline(
            source="example",
            title="Original",
            link="https://example.com/a",
            published_at=None,
            fetched_at=FETCHED,
        )
        edited = Headline(
            source="example",
            title="Rewritten entirely",
            link="https://example.com/a",
            published_at=None,
            fetched_at=FETCHED + DAY,
        )
        assert first.item_id == edited.item_id
        assert len(deduplicate([first, edited])) == 1


class TestSentimentRule:
    def test_extreme_fear_is_bought_and_extreme_greed_is_sold(self) -> None:
        rule = SentimentExtreme()
        assert rule.decide(_with_sentiment(Decimal(10))) is Decision.LONG
        assert rule.decide(_with_sentiment(Decimal(90))) is Decision.SHORT
        assert rule.decide(_with_sentiment(Decimal(50))) is Decision.FLAT

    def test_a_missing_reading_is_not_neutral(self) -> None:
        """None read as 50 would make a broken feed look like a calm market."""
        assert SentimentExtreme().decide(_with_sentiment(None)) is Decision.FLAT

    def test_impossible_bands_are_refused(self) -> None:
        with pytest.raises(ValueError, match="fear < greed"):
            SentimentExtreme(fear=Decimal(80), greed=Decimal(20))
