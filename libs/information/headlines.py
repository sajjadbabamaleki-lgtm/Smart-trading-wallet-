"""Crypto news headlines, from the outlets' own RSS feeds.

Free, no key, no quota, no terms to negotiate — an outlet that publishes a feed
is inviting readers, and this reads it the way a reader would.

**It can only collect forward, and that is the whole cost of this route.** A
feed carries its last twenty to fifty items, so there is no archive to
backtest against: a headline signal has to be gathered for weeks before it can
be judged at all. The alternative was a paid historical news archive, and the
honest trade is to start collecting today rather than to wait for a budget.

**Three timestamps, and the difference between them is the point.** An outlet
claims a publication time; the item becomes visible on the feed at some later
moment; we fetch it later still. A decision at time T may use only what we had
at T, so every item stores our own fetch time and every point-in-time query
selects on that — not on the outlet's claim, which can be backdated, wrong, or
simply generous about when a story really went out.

This is ADR-007's receipt-time rule applied to text. It matters more here than
for market data, because a feed can publish an item hours after its stated
time and a backtest that trusted the stated time would be reading the news
before it was news.

**Nothing here interprets anything.** It collects headlines and stores them.
Reading them — deciding whether an item is bullish, whether it is already
priced in, whether it matters at all — is a separate job for a language model,
and mixing the two would make a collection bug look like a judgement error.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Final
from xml.etree import ElementTree

import httpx

REQUEST_TIMEOUT_SECONDS: Final = 20.0

FEEDS: Final = {
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
    "decrypt": "https://decrypt.co/feed",
    "theblock": "https://www.theblock.co/rss.xml",
}
"""The outlets read, and why these.

Four general crypto outlets with working public feeds, chosen for coverage
rather than for quality of analysis: what matters for a signal is whether an
event was reported and when, not whether the piece was any good. Adding an
outlet is a line here; the storage and the point-in-time rules do not change.
"""

MAX_TITLE_LENGTH: Final = 500
"""Longer than any headline and short enough to bound a bad feed."""


class FeedError(RuntimeError):
    """A feed this module will not interpret."""


@dataclass(frozen=True, slots=True)
class Headline:
    """One item from a feed, as published and as received."""

    source: str
    title: str
    link: str
    published_at: datetime | None
    """The outlet's claim. None when the feed omitted or mangled it."""
    fetched_at: datetime
    """When we received it. The only time a point-in-time query may use."""

    @property
    def item_id(self) -> str:
        """A stable identity for deduplication.

        The link, hashed. Feeds reuse `guid` inconsistently and some omit it,
        while the link is present in every item this module accepts and does
        not change when an outlet edits a headline — so an edited story
        deduplicates against its original rather than arriving as news twice.
        """
        return hashlib.sha256(self.link.encode()).hexdigest()

    @property
    def claimed_lag_seconds(self) -> float | None:
        """How long after its claimed publication we received it.

        Worth storing rather than computing later: a feed that routinely
        publishes items hours after their stated time is a feed whose stated
        times must not be trusted, and this is the number that shows it.
        """
        if self.published_at is None:
            return None
        return (self.fetched_at - self.published_at).total_seconds()


def _text(element: ElementTree.Element, tag: str) -> str | None:
    found = element.find(tag)
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


WHITESPACE: Final = re.compile(r"\s+")


def _clean(title: str) -> str:
    """Collapse whitespace and bound the length.

    Feeds arrive with newlines and runs of spaces inside titles, and two
    otherwise identical headlines differing only in whitespace would be stored
    as two stories.
    """
    return WHITESPACE.sub(" ", title).strip()[:MAX_TITLE_LENGTH]


def _published(element: ElementTree.Element) -> datetime | None:
    """The outlet's claimed time, if it gave a readable one.

    None rather than a guess. A missing publication time is a fact about the
    feed, and substituting the fetch time would erase the distinction this
    module exists to keep.
    """
    raw = _text(element, "pubDate")
    if raw is None:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_feed(xml: str, *, source: str, fetched_at: datetime) -> tuple[Headline, ...]:
    """Every item in one feed document.

    Tolerant of an item missing a title or a link — such an item is skipped,
    not raised on, because one malformed entry must not discard the other
    forty. A document that does not parse at all is a different matter and is
    refused.
    """
    try:
        root = ElementTree.fromstring(xml)  # noqa: S314 - feeds are XML, not untrusted schemas
    except ElementTree.ParseError as exc:
        raise FeedError(f"{source} did not return parsable XML: {exc}") from None

    headlines = []
    for item in root.iter("item"):
        title = _text(item, "title")
        link = _text(item, "link")
        if not title or not link:
            continue
        headlines.append(
            Headline(
                source=source,
                title=_clean(title),
                link=link,
                published_at=_published(item),
                fetched_at=fetched_at,
            )
        )
    return tuple(headlines)


async def fetch_feed(
    source: str,
    *,
    url: str | None = None,
    now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[Headline, ...]:
    """One outlet's current items."""
    endpoint = url or FEEDS.get(source)
    if endpoint is None:
        raise FeedError(f"no feed configured for {source!r}; known: {', '.join(FEEDS)}")

    fetched_at = now or datetime.now(tz=UTC)
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True)
    try:
        response = await http.get(endpoint)
        response.raise_for_status()
        body = response.text
    finally:
        if owns_client:
            await http.aclose()
    return parse_feed(body, source=source, fetched_at=fetched_at)


def deduplicate(headlines: Sequence[Headline]) -> tuple[Headline, ...]:
    """One item per link, keeping the earliest fetch.

    The earliest, because that is when we first knew — a later re-fetch of the
    same story is not new information and recording it as such would let one
    story count several times in a window.
    """
    earliest: dict[str, Headline] = {}
    for headline in headlines:
        held = earliest.get(headline.item_id)
        if held is None or headline.fetched_at < held.fetched_at:
            earliest[headline.item_id] = headline
    return tuple(sorted(earliest.values(), key=lambda item: item.fetched_at))
