"""
The pure tick -> candle aggregator: bucketing, out-of-order ticks, gaps,
multiple intervals. No DB, no broker, no asyncio.
"""
from api.candles import (
    INTERVALS, aggregate_ticks_to_candles, angel_interval_code,
    bucket_start, interval_seconds, is_valid_interval,
)
from datetime import datetime, timezone


def _tick(ts: str, ltp: float) -> dict:
    return {"ts": ts, "ltp": ltp}


def test_interval_metadata():
    assert is_valid_interval("5m")
    assert not is_valid_interval("7m")
    assert interval_seconds("5m") == 300
    assert angel_interval_code("5m") == "FIVE_MINUTE"
    assert interval_seconds("1d") == 86400
    assert angel_interval_code("1d") == "ONE_DAY"
    assert set(INTERVALS) == {"1m", "3m", "5m", "15m", "30m", "1h", "1d"}


def test_single_bucket_ohlc():
    ticks = [
        _tick("2026-11-18T10:00:00+00:00", 100.0),
        _tick("2026-11-18T10:00:30+00:00", 105.0),
        _tick("2026-11-18T10:01:00+00:00", 98.0),
        _tick("2026-11-18T10:04:59+00:00", 102.0),
    ]
    candles = aggregate_ticks_to_candles(ticks, "5m")
    assert len(candles) == 1
    c = candles[0]
    assert c["o"] == 100.0
    assert c["h"] == 105.0
    assert c["l"] == 98.0
    assert c["c"] == 102.0
    assert c["v"] is None


def test_two_buckets_rollover():
    ticks = [
        _tick("2026-11-18T10:00:00+00:00", 100.0),
        _tick("2026-11-18T10:04:59+00:00", 110.0),
        _tick("2026-11-18T10:05:00+00:00", 111.0),  # new bucket starts exactly on boundary
        _tick("2026-11-18T10:07:00+00:00", 108.0),
    ]
    candles = aggregate_ticks_to_candles(ticks, "5m")
    assert len(candles) == 2
    assert candles[0]["c"] == 110.0
    assert candles[1]["o"] == 111.0
    assert candles[1]["c"] == 108.0


def test_out_of_order_ticks_still_fold_into_high_low_but_respect_time_for_open_close():
    # Ticks arrive out of chronological order (e.g. two near-simultaneous
    # WS messages processed slightly out of sequence); open/close must still
    # reflect actual time order, while high/low fold in regardless of order.
    ticks = [
        _tick("2026-11-18T10:00:30+00:00", 105.0),  # arrives first in the list...
        _tick("2026-11-18T10:00:00+00:00", 100.0),  # ...but is actually earlier
        _tick("2026-11-18T10:00:45+00:00", 95.0),   # lowest, arrives last
        _tick("2026-11-18T10:00:50+00:00", 103.0),  # true close
    ]
    candles = aggregate_ticks_to_candles(ticks, "5m")
    assert len(candles) == 1
    c = candles[0]
    assert c["o"] == 100.0   # earliest by time, not by list position
    assert c["c"] == 103.0   # latest by time
    assert c["h"] == 105.0
    assert c["l"] == 95.0


def test_gap_produces_no_synthetic_candle():
    ticks = [
        _tick("2026-11-18T10:00:00+00:00", 100.0),
        # a full 15-minute gap -- three empty 5m buckets in between
        _tick("2026-11-18T10:15:00+00:00", 120.0),
    ]
    candles = aggregate_ticks_to_candles(ticks, "5m")
    assert len(candles) == 2  # not 4 -- the empty buckets are just absent
    assert candles[0]["c"] == 100.0
    assert candles[1]["o"] == 120.0


def test_empty_input():
    assert aggregate_ticks_to_candles([], "5m") == []


def test_ticks_missing_fields_are_skipped_not_crashed_on():
    ticks = [
        {"ts": "2026-11-18T10:00:00+00:00", "ltp": 100.0},
        {"ts": None, "ltp": 50.0},
        {"ts": "2026-11-18T10:00:10+00:00", "ltp": None},
        {"ts": "not-a-date", "ltp": 99.0},
    ]
    candles = aggregate_ticks_to_candles(ticks, "5m")
    assert len(candles) == 1
    assert candles[0]["o"] == 100.0
    assert candles[0]["c"] == 100.0


def test_bucket_start_floors_correctly():
    ts = datetime(2026, 11, 18, 10, 7, 43, tzinfo=timezone.utc)
    assert bucket_start(ts, "5m") == datetime(2026, 11, 18, 10, 5, 0, tzinfo=timezone.utc)
    assert bucket_start(ts, "1h") == datetime(2026, 11, 18, 10, 0, 0, tzinfo=timezone.utc)
    assert bucket_start(ts, "1d") == datetime(2026, 11, 18, 0, 0, 0, tzinfo=timezone.utc)


def test_naive_timestamp_is_treated_as_local_time_not_utc():
    """
    database.py stores every timestamp as naive LOCAL time (datetime.now(),
    no tzinfo) -- that's the one real convention in this codebase, so a
    naive tick must be interpreted the same way, not assumed to already be
    UTC. This compares a naive tick against an explicit-offset tick built
    from this machine's *actual* local UTC offset (queried at run time, not
    hardcoded to IST or any other zone) -- the two must bucket identically.
    """
    offset = datetime.now().astimezone().utcoffset()
    naive_tick = _tick("2026-11-18T10:00:00", 100.0)
    explicit_local_tick = _tick(
        datetime(2026, 11, 18, 10, 0, 0, tzinfo=timezone(offset)).isoformat(), 100.0,
    )
    assert aggregate_ticks_to_candles([naive_tick], "1m") == \
        aggregate_ticks_to_candles([explicit_local_tick], "1m")
