"""FastAPI Application entry point for the Token-Bucket Rate Limiter service."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, AsyncGenerator

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.limiter import RateLimitDecision, TokenBucketLimiter
from app.schemas import (
    HealthResponse,
    LimiterStatusResponse,
    RateLimitRequest,
    RateLimitResponse,
)

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("rate_limiter.api")

# Static directory path
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"

# Global limiter instance
limiter_instance = TokenBucketLimiter()


def get_limiter(request: Request) -> TokenBucketLimiter:
    """Dependency provider for TokenBucketLimiter instance."""
    # Allow overriding via app.state (useful in tests)
    if hasattr(request.app.state, "limiter"):
        return request.app.state.limiter
    return limiter_instance


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for application startup and shutdown."""
    logger.info("Starting Token-Bucket Rate Limiter Service...")
    app.state.limiter = limiter_instance
    yield
    logger.info("Shutting down Token-Bucket Rate Limiter Service...")


app = FastAPI(
    title="Token-Bucket Rate Limiter API",
    description=(
        "A lightweight, thread-safe in-memory Token-Bucket Rate Limiter service "
        "built with Python and FastAPI."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files directory if available
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get(
    "/",
    response_class=HTMLResponse,
    summary="Interactive Rate Limiter Dashboard & Presentation",
    tags=["Frontend"],
)
async def serve_dashboard() -> HTMLResponse:
    """Serve the interactive Token-Bucket rate limiter dashboard and presentation."""
    if INDEX_HTML.exists():
        content = INDEX_HTML.read_text(encoding="utf-8")
        return HTMLResponse(content=content, status_code=status.HTTP_200_OK)
    return HTMLResponse(
        content="<h1>Token-Bucket Rate Limiter</h1><p>Frontend template not found.</p>",
        status_code=status.HTTP_200_OK,
    )


@app.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health Check",
    tags=["Health"],
)
async def health_check() -> HealthResponse:
    """Return the health status of the rate limiter service."""
    return HealthResponse(
        status="healthy",
        service="token-bucket-rate-limiter",
        version="1.0.0",
    )


@app.get(
    "/v1/limiter/status",
    response_model=LimiterStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Real-Time Limiter Telemetry",
    tags=["Telemetry"],
)
async def get_limiter_status(
    limiter: Annotated[TokenBucketLimiter, Depends(get_limiter)],
) -> LimiterStatusResponse:
    """Retrieve real-time metrics and dynamic token bucket states directly from the limiter engine."""
    data = limiter.get_status()
    return LimiterStatusResponse(**data)


@app.delete(
    "/v1/limiter/reset",
    status_code=status.HTTP_200_OK,
    summary="Reset All Buckets and Counters",
    tags=["Telemetry"],
)
async def reset_limiter_state(
    limiter: Annotated[TokenBucketLimiter, Depends(get_limiter)],
) -> dict[str, str]:
    """Clear all active buckets and reset telemetry counters to zero."""
    limiter.reset()
    return {"message": "All buckets and telemetry counters have been reset."}


@app.post(
    "/v1/limit/check",
    response_model=RateLimitResponse,
    status_code=status.HTTP_200_OK,
    summary="Evaluate Rate Limit",
    tags=["Rate Limiting"],
    responses={
        200: {
            "description": "Rate limit checked successfully. Request either allowed or denied.",
            "model": RateLimitResponse,
        },
        422: {
            "description": "Validation error for malformed or out-of-bounds parameters.",
        },
    },
)
async def check_rate_limit(
    payload: RateLimitRequest,
    limiter: Annotated[TokenBucketLimiter, Depends(get_limiter)],
) -> RateLimitResponse:
    """Evaluate whether a request should be allowed or denied using the token bucket algorithm.

    - **key**: Unique identifier (e.g. user ID, IP address, API key).
    - **rate_per_second**: Tokens refilled per second (positive finite float).
    - **burst**: Bucket capacity (positive integer).
    - **cost**: Tokens required for this request (positive integer <= burst, default 1).

    Returns HTTP 200 with `allowed: true` or `allowed: false` along with `remaining_tokens`
    and `retry_after_seconds`.
    """
    decision: RateLimitDecision = limiter.check(
        key=payload.key,
        rate_per_second=payload.rate_per_second,
        burst=payload.burst,
        cost=payload.cost,
    )

    logger.debug(
        "Key '%s' check: allowed=%s, remaining=%.2f, retry_after=%.2f",
        decision.key,
        decision.allowed,
        decision.remaining_tokens,
        decision.retry_after_seconds,
    )

    return RateLimitResponse(
        key=decision.key,
        allowed=decision.allowed,
        remaining_tokens=decision.remaining_tokens,
        retry_after_seconds=decision.retry_after_seconds,
        burst=decision.burst,
        rate_per_second=decision.rate_per_second,
    )
