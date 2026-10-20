"""Unit tests for the Token-Bucket Rate Limiter business logic.

Uses an injected deterministic fake clock to simulate elapsed time without sleeping.
"""

from __future__ import annotations

import concurrent.futures
from typing import List
import pytest

from app.limiter import TokenBucketLimiter


class FakeClock:
    """Controllable clock for deterministic time manipulation in tests."""

    def __init__(self, initial_time: float = 1000.0) -> None:
        self._current_time = initial_time

    def __call__(self) -> float:
        return self._current_time

    def advance(self, seconds: float) -> None:
        """Advance time forward by specified seconds."""
        if seconds < 0:
            raise ValueError("Time cannot move backward in FakeClock")
        self._current_time += seconds

    @property
    def current_time(self) -> float:
        return self._current_time


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock(initial_time=100.0)


@pytest.fixture
def limiter(fake_clock: FakeClock) -> TokenBucketLimiter:
    return TokenBucketLimiter(clock=fake_clock)


class TestTokenBucketLimiter:
    """Test suite for TokenBucketLimiter core algorithm."""

    def test_new_bucket_starts_at_full_capacity(
        self, limiter: TokenBucketLimiter, fake_clock: FakeClock
    ) -> None:
        """A newly encountered key must begin with full burst capacity."""
        decision = limiter.check(key="user-1", rate_per_second=2.0, burst=5, cost=1)
        assert decision.allowed is True
        # Burst was 5, cost was 1, so remaining should be 4
        assert decision.remaining_tokens == 4.0
        assert decision.retry_after_seconds == 0.0
        assert decision.burst == 5
        assert decision.rate_per_second == 2.0

    def test_requests_allowed_while_tokens_remain(
        self, limiter: TokenBucketLimiter
    ) -> None:
        """Subsequent requests within burst capacity are allowed."""
        # 5 capacity: 5 requests of cost 1 should all succeed
        for expected_remaining in [4.0, 3.0, 2.0, 1.0, 0.0]:
            d = limiter.check(key="user-burst", rate_per_second=1.0, burst=5, cost=1)
            assert d.allowed is True
            assert d.remaining_tokens == expected_remaining
            assert d.retry_after_seconds == 0.0

    def test_request_denied_when_insufficient_tokens(
        self, limiter: TokenBucketLimiter
    ) -> None:
        """Requests exceeding available tokens are denied without token deduction."""
        # Consume all 5 tokens
        for _ in range(5):
            limiter.check(key="user-drain", rate_per_second=1.0, burst=5, cost=1)

        # 6th request should fail
        denied = limiter.check(key="user-drain", rate_per_second=1.0, burst=5, cost=1)
        assert denied.allowed is False
        assert denied.remaining_tokens == 0.0
        # 1 token missing, rate is 1.0 token/sec -> retry_after should be 1.0 sec
        assert denied.retry_after_seconds == 1.0

        # Verify denied request DID NOT deduct tokens (still 0 tokens)
        denied_again = limiter.check(key="user-drain", rate_per_second=1.0, burst=5, cost=1)
        assert denied_again.allowed is False
        assert denied_again.remaining_tokens == 0.0

    def test_burst_capacity_enforced_tokens_do_not_exceed(
        self, limiter: TokenBucketLimiter, fake_clock: FakeClock
    ) -> None:
        """Tokens should never exceed burst capacity even if a lot of time passes."""
        # Drain 2 tokens from 5
        limiter.check(key="user-cap", rate_per_second=2.0, burst=5, cost=2)
        # Advance clock by 1000 seconds
        fake_clock.advance(1000.0)

        # Consume 1 token: bucket should be capped at 5, so remaining is 4
        d = limiter.check(key="user-cap", rate_per_second=2.0, burst=5, cost=1)
        assert d.allowed is True
        assert d.remaining_tokens == 4.0

    def test_tokens_refill_correctly_as_time_advances(
        self, limiter: TokenBucketLimiter, fake_clock: FakeClock
    ) -> None:
        """Tokens refill according to rate_per_second * elapsed_time."""
        # Burst 10, drain all 10
        limiter.check(key="refill-test", rate_per_second=2.0, burst=10, cost=10)

        # Denied immediately
        d0 = limiter.check(key="refill-test", rate_per_second=2.0, burst=10, cost=1)
        assert d0.allowed is False
        assert d0.remaining_tokens == 0.0

        # Advance 1.5 seconds -> 1.5 * 2.0 = 3 tokens refilled
        fake_clock.advance(1.5)

        # Cost of 2 should be allowed, leaving 3 - 2 = 1 token
        d1 = limiter.check(key="refill-test", rate_per_second=2.0, burst=10, cost=2)
        assert d1.allowed is True
        assert d1.remaining_tokens == 1.0

    def test_retry_after_calculation(
        self, limiter: TokenBucketLimiter
    ) -> None:
        """Retry after calculation must equal missing_tokens / rate_per_second."""
        # Burst 4, rate 2.0 (i.e. 1 token every 0.5s)
        # Drain all 4 tokens
        limiter.check(key="retry-test", rate_per_second=2.0, burst=4, cost=4)

        # Request cost 3 when 0 available: missing 3 tokens -> 3 / 2.0 = 1.5s
        d = limiter.check(key="retry-test", rate_per_second=2.0, burst=4, cost=3)
        assert d.allowed is False
        assert d.remaining_tokens == 0.0
        assert d.retry_after_seconds == 1.5

    def test_independent_keys_maintain_separate_state(
        self, limiter: TokenBucketLimiter
    ) -> None:
        """Actions on key A must not affect key B."""
        # Key A drains completely
        limiter.check(key="key-a", rate_per_second=1.0, burst=3, cost=3)
        denied_a = limiter.check(key="key-a", rate_per_second=1.0, burst=3, cost=1)
        assert denied_a.allowed is False

        # Key B should still be untouched and allowed
        allowed_b = limiter.check(key="key-b", rate_per_second=1.0, burst=3, cost=1)
        assert allowed_b.allowed is True
        assert allowed_b.remaining_tokens == 2.0

    def test_policy_change_does_not_reset_bucket_to_full(
        self, limiter: TokenBucketLimiter, fake_clock: FakeClock
    ) -> None:
        """Updating burst or rate policy does not unexpectedly refill the bucket to full."""
        # Key starts with burst 10, consumes 8 tokens -> 2 tokens left
        limiter.check(key="policy-user", rate_per_second=1.0, burst=10, cost=8)

        # Policy changes to burst 20, rate 5.0 immediately without time passing
        # Bucket had 2 tokens left, so it should NOT jump to 20 tokens!
        # With cost=2, it consumes the 2 remaining tokens -> remaining=0
        d = limiter.check(key="policy-user", rate_per_second=5.0, burst=20, cost=2)
        assert d.allowed is True
        assert d.remaining_tokens == 0.0
        assert d.burst == 20
        assert d.rate_per_second == 5.0

        # Further request without time passing must be denied
        d2 = limiter.check(key="policy-user", rate_per_second=5.0, burst=20, cost=1)
        assert d2.allowed is False
        assert d2.retry_after_seconds == 0.2  # 1 / 5.0

    def test_policy_change_clamps_tokens_to_reduced_burst(
        self, limiter: TokenBucketLimiter
    ) -> None:
        """If burst policy is reduced below current tokens, tokens clamp to new burst."""
        # Key starts with burst 10, cost 1 -> 9 tokens remain
        limiter.check(key="clamp-user", rate_per_second=1.0, burst=10, cost=1)

        # Policy changes to burst 4
        # Tokens should clamp from 9 down to 4.
        # Cost 3 consumed -> remaining = 1
        d = limiter.check(key="clamp-user", rate_per_second=1.0, burst=4, cost=3)
        assert d.allowed is True
        assert d.remaining_tokens == 1.0
        assert d.burst == 4

    def test_zero_or_negative_elapsed_time_handling(
        self, limiter: TokenBucketLimiter, fake_clock: FakeClock
    ) -> None:
        """Clock anomalies or concurrent calls at the exact same timestamp are handled."""
        limiter.check(key="no-time", rate_per_second=1.0, burst=5, cost=1)
        # Check again at same clock tick
        d = limiter.check(key="no-time", rate_per_second=1.0, burst=5, cost=1)
        assert d.allowed is True
        assert d.remaining_tokens == 3.0

    def test_reset_clears_all_buckets(self, limiter: TokenBucketLimiter) -> None:
        """Reset clears all buckets in limiter."""
        limiter.check(key="k1", rate_per_second=1.0, burst=5, cost=1)
        limiter.check(key="k2", rate_per_second=1.0, burst=5, cost=1)
        assert limiter.bucket_count == 2
        limiter.reset()
        assert limiter.bucket_count == 0

    def test_concurrent_access_thread_safety(self) -> None:
        """Simultaneous concurrent requests to same key do not corrupt state or over-allocate."""
        # Use real limiter without fake clock for thread stress test
        real_limiter = TokenBucketLimiter()
        burst = 100
        total_threads = 50
        requests_per_thread = 4
        # Total attempted cost = 50 * 4 = 200 > burst (100)

        results: List[bool] = []
        lock = concurrent.futures.ThreadPoolExecutor(max_workers=10)

        def make_request() -> bool:
            decision = real_limiter.check(
                key="concurrent-key",
                rate_per_second=0.001,  # negligible refill during test
                burst=burst,
                cost=1,
            )
            return decision.allowed

        with lock as executor:
            futures = [executor.submit(make_request) for _ in range(total_threads * requests_per_thread)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        allowed_count = sum(1 for r in results if r is True)
        denied_count = sum(1 for r in results if r is False)

        # Because burst is 100 and refill rate is negligible, allowed count must be exactly burst (100)
        assert allowed_count == burst
        assert denied_count == 100
        assert len(results) == 200

    def test_get_bucket_retrieval(self, limiter: TokenBucketLimiter) -> None:
        """get_bucket retrieves existing bucket or returns None if absent."""
        assert limiter.get_bucket("unknown") is None
        limiter.check(key="known", rate_per_second=1.0, burst=5, cost=1)
        bucket = limiter.get_bucket("known")
        assert bucket is not None
        assert bucket.key == "known"
        assert bucket.burst == 5

    def test_clock_moving_backward_safely_handled(self) -> None:
        """If monotonic time provider jumps backwards, elapsed time clamps to zero without corruption."""
        current_time = 200.0

        def shifting_clock() -> float:
            return current_time

        limiter = TokenBucketLimiter(clock=shifting_clock)
        # First request at t = 200.0
        d1 = limiter.check(key="back-clock", rate_per_second=2.0, burst=5, cost=2)
        assert d1.allowed is True
        assert d1.remaining_tokens == 3.0

        # Clock unexpectedly goes backwards to t = 150.0
        current_time = 150.0
        d2 = limiter.check(key="back-clock", rate_per_second=2.0, burst=5, cost=1)
        assert d2.allowed is True
        # Tokens should not become negative or refill backwards; elapsed is clamped to 0.0
        assert d2.remaining_tokens == 2.0

    def test_fractional_rates_and_micro_refill(self, fake_clock: FakeClock) -> None:
        """Limiter correctly handles small fractional rates and accurate retry_after."""
        limiter = TokenBucketLimiter(clock=fake_clock)
        # 0.5 tokens/sec (1 token every 2 seconds)
        limiter.check(key="slow-refill", rate_per_second=0.5, burst=2, cost=2)

        # Denied
        denied = limiter.check(key="slow-refill", rate_per_second=0.5, burst=2, cost=1)
        assert denied.allowed is False
        assert denied.retry_after_seconds == 2.0  # 1 / 0.5 = 2.0s

        # Advance 1.0 second -> 0.5 tokens added
        fake_clock.advance(1.0)
        denied_half = limiter.check(key="slow-refill", rate_per_second=0.5, burst=2, cost=1)
        assert denied_half.allowed is False
        assert denied_half.remaining_tokens == 0.5
        assert denied_half.retry_after_seconds == 1.0  # (1 - 0.5) / 0.5 = 1.0s

    def test_get_status_telemetry(self, limiter: TokenBucketLimiter) -> None:
        """get_status reports total_requests, allowed, denied, and buckets info."""
        limiter.check(key="stat-1", rate_per_second=1.0, burst=5, cost=1)
        # Denied request
        limiter.check(key="stat-1", rate_per_second=1.0, burst=5, cost=5)

        status = limiter.get_status()
        assert status["total_requests"] == 2
        assert status["total_allowed"] == 1
        assert status["total_denied"] == 1
        assert status["total_keys"] == 1
        assert len(status["buckets"]) == 1
        assert status["buckets"][0]["key"] == "stat-1"

        # Reset clears counters
        limiter.reset()
        clean = limiter.get_status()
        assert clean["total_requests"] == 0
        assert clean["total_keys"] == 0


