"""Inputs that are not derived from the price series.

The organising principle came out of this project's own results. Every signal
tested so far — moving averages, RSI, MACD, funding extremes — is computed from
public data by a published formula, so everyone who wants it has it. One of
them demonstrably worked in 2021-2023 and was competed away by 2026, and that
decay is the mechanism by which any such signal ends.

What is left has to be information that is not uniformly available, or not
uniformly interpreted. This package holds those inputs: market sentiment
indices, news headlines, and later a language model's reading of them. They are
kept apart from `libs/exchange/` because they are not venue data and from
`libs/domain/` because they are not core concepts — they are outside
information, with the accuracy and availability problems that come with it.

**Point-in-time is harder here than anywhere else.** A candle's timestamp is
unambiguous. A news item has a publication time the outlet claims, a time it
became visible on the feed, and a time we fetched it, and they can differ by
hours. Every store in this package therefore keeps our own receipt time
alongside the source's claimed time, per ADR-007, and every point-in-time query
selects on ours — because what a decision at time T may use is what we had at
time T, not what the world had published by then.
"""
