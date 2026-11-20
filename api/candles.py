"""
Candle interval metadata, and the pure tick -> OHLCV aggregator.

Kept dependency-free (no DB, no broker, no asyncio) so it's trivially unit
testable: out-of-order ticks, gaps, bucketing, session boundaries are all
properties of this module alone.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class IntervalSpec:
    seconds: int
    angel_code: str  # the string Angel's getCandleData expects


# Our own interval vocabulary (what the REST API and the terminal use) ->
# how long a bucket is, and what Angel calls it. "10m" isn't in the UI's
# timeframe list but Angel supports it; left out here to match the spec's
# own timeframe bar exactly (1m,3m,5m,15m,30m,1h,1d).
INTERVALS: Dict[str, IntervalSpec] = {
    "1m": IntervalSpec(60, "ONE_MINUTE"),
    "3m": IntervalSpec(180, "THREE_MINUTE"),
    "5m": IntervalSpec(300, "FIVE_MINUTE"),
    "15m": IntervalSpec(900, "FIFTEEN_MINUTE"),
    "30m": IntervalSpec(1800, "THIRTY_MINUTE"),
    "1h": IntervalSpec(3600, "ONE_HOUR"),
    "1d": IntervalSpec(86400, "ONE_DAY"),
}


def is_valid_interval(interval: str) -> bool:
    return interval in INTERVALS


def interval_seconds(interval: str) -> int:
    return INTERVALS[interval].seconds


def angel_interval_code(interval: str) -> str:
    return INTERVALS[interval].angel_code


def _parse_ts(ts: Any) -> Optional[datetime]:
    """
    Accepts an ISO string or a datetime; returns a tz-aware UTC datetime.

    A naive value is presumed to be local wall-clock time, not UTC -- that's
    the convention database.py uses everywhere (tick_history.ts, trades.*_time,
    etc. are all `datetime.now().isoformat()`, no tzinfo). datetime.astimezone()
    on a naive instance attaches the system's local tzinfo without shifting
    the clock value, which is exactly the conversion needed before moving it
    to UTC for bucket math.
    """
    if isinstance(ts, datetime):
        dt = ts
    elif isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc)


def bucket_start(ts: datetime, interval: str) -> datetime:
    """floor(ts, interval) -- the start of the candle this tick belongs to."""
    secs = interval_seconds(interval)
    epoch = int(ts.timestamp())
    floored = (epoch // secs) * secs
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def aggregate_ticks_to_candles(ticks: List[Dict[str, Any]], interval: str) -> List[Dict[str, Any]]:
    """
    Bucket raw {ltp, ts} ticks into OHLC candles at the given interval.

    - Ticks are sorted by time first, so open/close are correct even if the
      caller's rows arrived out of chronological order (SQLite ORDER BY ts
      should already guarantee this, but a pure function shouldn't assume
      its input was pre-sorted by someone else).
    - Within one bucket, high/low fold in every tick regardless of order --
      an out-of-order tick still correctly extends the bucket's range.
    - An interval with zero ticks produces no candle at all (a gap is left
      as a gap, never a synthesized flat candle).
    - Volume is None: ticks are LTP-only, there is no per-tick traded
      quantity to sum, and reporting a volume here would be fabricated.

    Returns candles sorted by bucket start, oldest first, each
    {ts (bucket start, ISO), o, h, l, c, v: None}.
    """
    parsed = []
    for t in ticks:
        dt = _parse_ts(t.get("ts"))
        ltp = t.get("ltp")
        if dt is None or ltp is None:
            continue
        parsed.append((dt, float(ltp)))

    if not parsed:
        return []

    parsed.sort(key=lambda p: p[0])

    buckets: "dict[datetime, dict]" = {}
    order: List[datetime] = []
    for dt, ltp in parsed:
        b = bucket_start(dt, interval)
        if b not in buckets:
            buckets[b] = {"o": ltp, "h": ltp, "l": ltp, "c": ltp}
            order.append(b)
        else:
            cur = buckets[b]
            cur["h"] = max(cur["h"], ltp)
            cur["l"] = min(cur["l"], ltp)
            cur["c"] = ltp  # ticks are time-sorted, so the last write is the true close

    return [
        {"ts": b.isoformat(timespec="seconds").replace("+00:00", "Z"),
         "o": buckets[b]["o"], "h": buckets[b]["h"], "l": buckets[b]["l"],
         "c": buckets[b]["c"], "v": None}
        for b in order
    ]
