"""In-memory, thread-safe Token-Bucket Rate Limiter implementation.

Note:
    In-memory state is lost when the service restarts and is not shared across
    multiple worker processes or instances.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, NamedTuple

logger = logging.getLogger(__name__)


class RateLimitDecision(NamedTuple):
    """Result of a token-bucket rate limit evaluation."""

    key: str
    allowed: bool
    remaining_tokens: float
    retry_after_seconds: float
    burst: int
    rate_per_second: float


@dataclass
class TokenBucket:
    """Represents the internal state of a single rate limit bucket."""

    key: str
    tokens: float
    burst: int
    rate_per_second: float
    last_refill_timestamp: float
    lock: threading.Lock = field(default_factory=threading.Lock)


class TokenBucketLimiter:
    """Thread-safe in-memory Token Bucket rate limiter.

    Features:
    - Per-key independent token buckets.
    - Deterministic time injection via callable clock.
    - Thread synchronization using fine-grained per-bucket locks.
    - Dynamic policy adjustment (updating rate or burst capacity without
      resetting bucket to full).
    - Real-time telemetry tracking (total requests, allowed, denied, and active bucket balances).
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        """Initialize the rate limiter.

        Args:
            clock: Monotonic timestamp provider. Defaults to time.monotonic.
        """
        self._clock: Callable[[], float] = clock if clock is not None else time.monotonic
        self._buckets: dict[str, TokenBucket] = {}
        self._registry_lock: threading.Lock = threading.Lock()
        self._stats_lock: threading.Lock = threading.Lock()
        self._total_requests: int = 0
        self._total_allowed: int = 0
        self._total_denied: int = 0

    def check(
        self,
        key: str,
        rate_per_second: float,
        burst: int,
        cost: int = 1,
    ) -> RateLimitDecision:
        """Evaluate whether a request with a given cost should be allowed.

        Algorithm steps:
        1. Look up existing bucket or initialize a new bucket at full capacity.
        2. With bucket lock acquired:
           a. Calculate elapsed time since last refill.
           b. Refill tokens: tokens += elapsed * rate_per_second.
           c. If burst or rate policy changed, apply new policy and clamp existing
              tokens to new burst capacity without resetting to full.
           d. Update last_refill_timestamp to current time.
           e. Check if tokens >= cost:
              - If yes: deduct cost, allow request, retry_after = 0.0.
              - If no: do not deduct tokens, deny request, calculate retry_after.

        Args:
            key: Rate limit key identifier.
            rate_per_second: Configured tokens added per second.
            burst: Configured maximum token burst capacity.
            cost: Tokens required for this request.

        Returns:
            RateLimitDecision containing evaluation details.
        """
        now = self._clock()

        # Step 1: Thread-safe retrieval or creation of bucket
        with self._registry_lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                # Newly encountered key starts with a full token bucket
                bucket = TokenBucket(
                    key=key,
                    tokens=float(burst),
                    burst=burst,
                    rate_per_second=rate_per_second,
                    last_refill_timestamp=now,
                )
                self._buckets[key] = bucket
                logger.debug("Created new bucket for key '%s' with burst=%d", key, burst)

        # Step 2: Thread-safe bucket state update and decision
        with bucket.lock:
            elapsed = max(0.0, now - bucket.last_refill_timestamp)

            # Refill using the previous rate up to previous capacity
            refilled_tokens = min(
                float(bucket.burst),
                bucket.tokens + (elapsed * bucket.rate_per_second),
            )

            # Handle policy changes dynamically without resetting to full
            if bucket.burst != burst or bucket.rate_per_second != rate_per_second:
                logger.info(
                    "Updating policy for key '%s': burst %d->%d, rate %.2f->%.2f",
                    key,
                    bucket.burst,
                    burst,
                    bucket.rate_per_second,
                    rate_per_second,
                )
                bucket.burst = burst
                bucket.rate_per_second = rate_per_second
                # Clamp existing tokens to new burst capacity
                bucket.tokens = min(float(burst), refilled_tokens)
            else:
                bucket.tokens = refilled_tokens

            bucket.last_refill_timestamp = now

            # Evaluate cost
            if bucket.tokens >= cost:
                bucket.tokens -= cost
                allowed = True
                retry_after_seconds = 0.0
            else:
                allowed = False
                missing_tokens = cost - bucket.tokens
                retry_after_seconds = missing_tokens / bucket.rate_per_second

            # Ensure non-negative remaining tokens and retry after values
            remaining_tokens = max(0.0, bucket.tokens)
            retry_after_seconds = max(0.0, retry_after_seconds)

        # Update telemetry statistics
        with self._stats_lock:
            self._total_requests += 1
            if allowed:
                self._total_allowed += 1
            else:
                self._total_denied += 1

        return RateLimitDecision(
            key=key,
            allowed=allowed,
            remaining_tokens=round(remaining_tokens, 4),
            retry_after_seconds=round(retry_after_seconds, 4),
            burst=bucket.burst,
            rate_per_second=bucket.rate_per_second,
        )

    def get_status(self) -> dict[str, Any]:
        """Return real-time telemetry and state of all active token buckets."""
        now = self._clock()
        buckets_list = []
        with self._registry_lock:
            keys = list(self._buckets.keys())

        for k in keys:
            with self._registry_lock:
                bucket = self._buckets.get(k)
            if bucket:
                with bucket.lock:
                    elapsed = max(0.0, now - bucket.last_refill_timestamp)
                    current_tokens = min(
                        float(bucket.burst),
                        bucket.tokens + (elapsed * bucket.rate_per_second),
                    )
                    buckets_list.append({
                        "key": bucket.key,
                        "tokens": round(max(0.0, current_tokens), 4),
                        "burst": bucket.burst,
                        "rate_per_second": bucket.rate_per_second,
                        "last_refill_timestamp": round(bucket.last_refill_timestamp, 4),
                    })

        with self._stats_lock:
            return {
                "total_keys": len(buckets_list),
                "total_requests": self._total_requests,
                "total_allowed": self._total_allowed,
                "total_denied": self._total_denied,
                "buckets": buckets_list,
            }

    def reset(self) -> None:
        """Clear all bucket states and reset telemetry counters."""
        with self._registry_lock:
            self._buckets.clear()
        with self._stats_lock:
            self._total_requests = 0
            self._total_allowed = 0
            self._total_denied = 0

    def get_bucket(self, key: str) -> TokenBucket | None:
        """Retrieve bucket instance if it exists (primarily for testing and inspection)."""
        with self._registry_lock:
            return self._buckets.get(key)

    @property
    def bucket_count(self) -> int:
        """Return the number of active buckets in memory."""
        with self._registry_lock:
            return len(self._buckets)
