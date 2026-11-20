import time

import pytest

from api.ratelimit import TokenBucket


@pytest.mark.asyncio
async def test_bucket_allows_burst_up_to_capacity():
    bucket = TokenBucket(rate_per_sec=1, capacity=3)
    start = time.monotonic()
    for _ in range(3):
        await bucket.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.1  # a full capacity burst shouldn't wait at all


@pytest.mark.asyncio
async def test_bucket_throttles_beyond_capacity():
    bucket = TokenBucket(rate_per_sec=10, capacity=1)
    start = time.monotonic()
    await bucket.acquire()  # consumes the only token immediately
    await bucket.acquire()  # must wait ~1/10s for the next one
    elapsed = time.monotonic() - start
    assert elapsed >= 0.08  # allow a little scheduling slack under 0.1s
