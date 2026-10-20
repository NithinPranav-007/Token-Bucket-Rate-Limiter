# Project Intent: Token-Bucket Rate Limiter REST API

## What to Build
A lightweight, high-performance, thread-safe in-memory Token-Bucket Rate Limiter REST API using Python 3 and FastAPI. The service evaluates client requests against dynamically configurable rate limits (burst capacity, refill rate per second, and token cost) and returns whether the request is allowed or denied along with remaining tokens and computed retry-after intervals.

## Who Uses It
- Backend microservices, API gateways, and upstream proxies requiring fast rate-limiting decisions.
- Distributed or monolithic application components managing per-user, per-IP, or per-tenant traffic shaping.
- Developers needing an embedded or standalone reference implementation of the token-bucket algorithm without heavyweight external dependencies like Redis.

## Must-Have Behaviors
1. **Accurate Token-Bucket Algorithm**:
   - Initial state for any newly observed key starts with a full bucket (`tokens == burst`).
   - Refills tokens continuously using monotonic elapsed time multiplied by `rate_per_second`.
   - Never exceeds the configured burst capacity ceiling.
   - Allows requests when available tokens are greater than or equal to `cost`, deducting `cost`.
   - Denies requests when tokens are less than `cost`, without deducting tokens.
   - Returns retry-after delay calculated as `(cost - tokens) / rate_per_second` on denial.
2. **Policy Adaptability**:
   - Dynamic changes to `burst` or `rate_per_second` for an existing key must not reset the bucket to full.
   - Refills tokens based on prior rate, applies the new rate, and clamps existing tokens to the new burst limit.
3. **Thread Safety & State Isolation**:
   - Distinct keys must maintain strictly isolated bucket states.
   - Concurrent requests to the same key or across keys must be protected against race conditions using synchronization locks.
4. **API Endpoints**:
   - `GET /health`: Returns service health status and version (HTTP 200).
   - `POST /v1/limit/check`: Validates input, evaluates rate limit, returns HTTP 200 with allow/deny decision. Malformed or invalid input returns HTTP 422.
5. **Deterministic Testing**:
   - Injectable monotonic clock support to allow instant, flake-free simulated time progression in automated tests without real-time sleep.

## Out of Scope
- External databases or persistence layers (Redis, PostgreSQL, etc.).
- Cross-process distributed state sharing across multiple worker processes.
- User accounts, authentication, authorization, or API key management.
- Frontend web applications, dashboards, or UI components.
- Cloud deployment scripts, Kubernetes manifests, or Terraform infrastructure code.
- Metrics collectors (Prometheus, StatsD), billing/payment systems, or proxy middlewares.

## Run Configuration
- **Runtime**: Python 3.9+
- **Framework**: FastAPI with Uvicorn
- **Validation**: Pydantic v2
- **Testing**: pytest, httpx
- **Install command**: `python -m pip install -r requirements.txt`
- **Start command**: `python -m uvicorn app.main:app --reload`
- **Test command**: `python -m pytest -q`
