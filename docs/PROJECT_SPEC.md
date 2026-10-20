# Project Specification: Token-Bucket Rate Limiter REST API

## 1. Executive Summary

This document specifies the technical design, architectural patterns, algorithmic mechanisms, and operational constraints of the **Token-Bucket Rate Limiter REST API**.

The service provides a low-latency, in-memory rate-limiting engine accessible via standard HTTP REST endpoints. Rate limiting decisions are based on the classic **token-bucket algorithm**, permitting bursts up to a specified capacity while enforcing sustained throughput via continuous token refill over time.

---

## 2. Architecture & Component Design

The project strictly decouples presentation (HTTP transport and schema validation) from business logic (token-bucket state management and rate calculation).

```
                  ┌────────────────────────────────────────┐
                  │              HTTP Client               │
                  └───────────────────┬────────────────────┘
                                      │ JSON Request
                                      ▼
                  ┌────────────────────────────────────────┐
                  │             FastAPI App                │
                  │             (app/main.py)              │
                  └───────────────────┬────────────────────┘
                                      │ Validated Payload
                                      ▼
                  ┌────────────────────────────────────────┐
                  │          Pydantic Schemas              │
                  │            (app/schemas.py)            │
                  └───────────────────┬────────────────────┘
                                      │ rate, burst, cost
                                      ▼
                  ┌────────────────────────────────────────┐
                  │       TokenBucketLimiter Engine        │
                  │            (app/limiter.py)            │
                  │                                        │
                  │  ┌───────────────┐  ┌───────────────┐  │
                  │  │ Registry Lock │  │ Fake/Real     │  │
                  │  │               │  │ Monotonic Clck│  │
                  │  └───────────────┘  └───────────────┘  │
                  │  ┌───────────────────────────────────┐ │
                  │  │ In-Memory Key-to-Bucket Mapping   │ │
                  │  │ [key] -> TokenBucket(lock, ...)   │ │
                  │  └───────────────────────────────────┘ │
                  └───────────────────┬────────────────────┘
                                      │ RateLimitDecision
                                      ▼
                  ┌────────────────────────────────────────┐
                  │            HTTP Response               │
                  │    200 OK (Allowed / Denied) or 422    │
                  └────────────────────────────────────────┘
```

### Components:
1. **`app.schemas`**: Pydantic models with field constraints (`Field(gt=0)`) and model validators enforcing cross-field rules (e.g. `cost <= burst`, non-empty key, finite float rates).
2. **`app.limiter.TokenBucket`**: Per-key state model holding current token balance, burst ceiling, refill rate, last updated timestamp, and a dedicated reentrant/mutex synchronization lock.
3. **`app.limiter.TokenBucketLimiter`**: Central registry and evaluation engine managing bucket lifecycles, clock injection, dynamic policy adjustments, and concurrency control.
4. **`app.main`**: FastAPI application exposing `GET /health` and `POST /v1/limit/check`, handling dependency injection and standard logging.

---

## 3. Token-Bucket Algorithm Details

### 3.1 Mathematical Model
The token bucket algorithm maintains a balance of $T(t)$ tokens at time $t$ for a given key:

$$T(t) = \min\left(B, T(t_{\text{prev}}) + (t - t_{\text{prev}}) \times R\right)$$

Where:
- $B$: Burst capacity (positive integer ceiling).
- $R$: Refill rate (positive finite float tokens/second).
- $t$: Current monotonic time.
- $t_{\text{prev}}$: Timestamp of the previous token evaluation.
- $C$: Cost of the incoming request (tokens deducted if allowed).

### 3.2 Evaluation Lifecycle
1. **Key Discovery**:
   - If the key is encountered for the first time, a new bucket is allocated.
   - Initial state: $T(t_0) = B$, $t_{\text{prev}} = t_0$.
2. **Elapsed Time & Refill**:
   - Elapsed interval $\Delta t = \max(0.0, t - t_{\text{prev}})$.
   - Refilled tokens $T_{\text{refill}} = \min(B_{\text{current}}, T_{\text{prev}} + \Delta t \times R_{\text{current}})$.
3. **Dynamic Policy Handling**:
   - If incoming request supplies an updated burst ($B_{\text{new}} \neq B_{\text{current}}$) or rate ($R_{\text{new}} \neq R_{\text{current}}$):
     - Refill tokens using $R_{\text{current}}$ up to $B_{\text{current}}$.
     - Update $B_{\text{current}} \leftarrow B_{\text{new}}$ and $R_{\text{current}} \leftarrow R_{\text{new}}$.
     - Clamp current tokens: $T \leftarrow \min(B_{\text{new}}, T_{\text{refill}})$.
   - This prevents reset-to-full exploits when rate policies change.
4. **Decision Rule**:
   - If $T \ge C$:
     - $T \leftarrow T - C$
     - `allowed` = `True`
     - `retry_after_seconds` = `0.0`
   - If $T < C$:
     - Tokens are **not** deducted.
     - `allowed` = `False`
     - Missing tokens $M = C - T$.
     - `retry_after_seconds` = $M / R_{\text{current}}$.

---

## 4. State Management & Thread Synchronization

### 4.1 Locking Hierarchy
To ensure high throughput and prevent thread contention:
- **Registry Lock (`_registry_lock`)**: Protects dictionary additions and lookups (`_buckets`). It is held only during bucket lookup/initialization.
- **Per-Bucket Lock (`bucket.lock`)**: Each bucket has its own dedicated mutex. Multiple threads evaluating requests for *different* keys execute completely concurrently without blocking each other. Multiple threads accessing the *same* key serialize on that key's bucket lock, guaranteeing strict atomicity of the refill-and-deduct sequence.

### 4.2 Injected Clock
To avoid non-deterministic real-time sleeps in automated test suites, the `TokenBucketLimiter` accepts an optional `clock: Callable[[], float]` parameter. In production, this defaults to `time.monotonic`. In test environments, `FakeClock` allows advancing time instantaneously and deterministically.

---

## 5. Error Handling & Validation

| Condition | Status Code | Response Type | Explanation |
| :--- | :---: | :---: | :--- |
| Valid request, tokens available | 200 OK | `RateLimitResponse` | `allowed: true`, remaining tokens decreased. |
| Valid request, tokens insufficient | 200 OK | `RateLimitResponse` | `allowed: false`, remaining tokens unchanged, positive retry interval. |
| Empty / whitespace key | 422 Unprocessable Entity | Validation Error | Key must contain at least 1 non-whitespace character. |
| `rate_per_second <= 0` | 422 Unprocessable Entity | Validation Error | Refill rate must be greater than zero. |
| `rate_per_second` is NaN / Inf | 422 Unprocessable Entity | Validation Error | Refill rate must be a finite float. |
| `burst <= 0` | 422 Unprocessable Entity | Validation Error | Burst capacity must be a positive integer. |
| `cost <= 0` | 422 Unprocessable Entity | Validation Error | Token cost must be a positive integer (default 1). |
| `cost > burst` | 422 Unprocessable Entity | Validation Error | Request cost cannot exceed total bucket capacity. |

---

## 6. Assumptions & Known Limitations

1. **Process-Local Memory**:
   - All state is stored in an in-memory dictionary.
   - Restarting the service clears all buckets.
   - Running multiple Uvicorn workers (`--workers 4`) creates separate in-memory spaces for each process; keys will not share state across worker processes without an external synchronization store.
2. **Monotonicity**:
   - Time calculations rely on monotonic system clocks (`time.monotonic()`), preventing system wall-clock adjustments from corrupting rate limit tracking.
3. **No Automatic Garbage Collection of Expired Keys**:
   - Keys remain in memory once created. For production workloads with billions of ephemeral keys, a TTL-based eviction mechanism or LRU cache would be recommended.

---

## 7. Out of Scope Features
- Persistent distributed storage (Redis, Memcached, DynamoDB).
- Authentication, API keys, or OAuth2 token inspection.
- HTML frontend, monitoring dashboards, or UI templates.
- Web application firewalls or reverse proxy plugins.
- Container orchestrators or cloud deployment manifests.
