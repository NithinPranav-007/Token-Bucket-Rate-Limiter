"""Pydantic schemas for the Token-Bucket Rate Limiter API."""

from __future__ import annotations

import math
from typing import Annotated
from pydantic import BaseModel, Field, field_validator, model_validator


class RateLimitRequest(BaseModel):
    """Request schema for checking and consuming rate limit tokens."""

    key: Annotated[
        str,
        Field(
            min_length=1,
            description="Unique identifier for the rate-limited client or entity.",
            examples=["user-123"],
        ),
    ]
    rate_per_second: Annotated[
        float,
        Field(
            gt=0.0,
            description="Refill rate in tokens added per second. Must be finite and greater than zero.",
            examples=[2.0],
        ),
    ]
    burst: Annotated[
        int,
        Field(
            gt=0,
            description="Maximum burst capacity (token ceiling). Must be a positive integer.",
            examples=[5],
        ),
    ]
    cost: Annotated[
        int,
        Field(
            default=1,
            gt=0,
            description="Number of tokens requested. Must be positive and not exceed burst capacity.",
            examples=[1],
        ),
    ]

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        """Ensure key is not empty or just whitespace."""
        if not value or not value.strip():
            raise ValueError("Key must be a non-empty string")
        return value

    @field_validator("rate_per_second")
    @classmethod
    def validate_rate_per_second(cls, value: float) -> float:
        """Ensure rate_per_second is finite."""
        if not math.isfinite(value):
            raise ValueError("rate_per_second must be a finite number")
        return value

    @model_validator(mode="after")
    def validate_cost_against_burst(self) -> RateLimitRequest:
        """Ensure token cost does not exceed maximum burst capacity."""
        if self.cost > self.burst:
            raise ValueError(
                f"cost ({self.cost}) cannot exceed burst capacity ({self.burst})"
            )
        return self


class RateLimitResponse(BaseModel):
    """Response schema returned from rate limit evaluation."""

    key: str = Field(description="The key associated with this rate limit evaluation.")
    allowed: bool = Field(description="Whether the request is allowed or denied.")
    remaining_tokens: float = Field(
        description="Number of available tokens remaining in the bucket after this request."
    )
    retry_after_seconds: float = Field(
        description="Recommended wait time in seconds before sufficient tokens are available. 0.0 if allowed."
    )
    burst: int = Field(description="Configured burst capacity for this bucket.")
    rate_per_second: float = Field(description="Configured token refill rate per second.")


class HealthResponse(BaseModel):
    """Health check status response."""

    status: str = Field(default="healthy", description="Current health status of the service.")
    service: str = Field(
        default="token-bucket-rate-limiter",
        description="Name of the service.",
    )
    version: str = Field(default="1.0.0", description="Service semantic version.")


class BucketInfo(BaseModel):
    """Real-time state of an individual token bucket."""

    key: str = Field(description="Unique tenant/client identifier.")
    tokens: float = Field(description="Current real-time calculated token balance.")
    burst: int = Field(description="Burst capacity.")
    rate_per_second: float = Field(description="Refill rate per second.")
    last_refill_timestamp: float = Field(description="Monotonic timestamp of last refill.")


class LimiterStatusResponse(BaseModel):
    """Real-time observability and telemetry summary of the limiter engine."""

    total_keys: int = Field(description="Total number of active buckets in memory.")
    total_requests: int = Field(description="Total checks processed since startup.")
    total_allowed: int = Field(description="Total requests allowed.")
    total_denied: int = Field(description="Total requests denied.")
    buckets: list[BucketInfo] = Field(
        default_factory=list,
        description="Detailed list of all active buckets and their real-time state.",
    )

