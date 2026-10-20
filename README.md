# Token-Bucket Rate Limiter REST API

A lightweight, thread-safe in-memory Token-Bucket Rate Limiter REST API built with Python 3, FastAPI, and Pydantic.

The service provides real-time traffic policing using the **token-bucket algorithm**, allowing burst traffic while enforcing sustained rates over time, with zero external dependencies (no Redis, no external database).

---

## Features

- **Continuous Token Refill**: Refills tokens smoothly using monotonic elapsed time multiplied by the refill rate.
- **Dynamic Policy Updates**: Safely updates burst capacity and refill rate without wiping existing tokens or resetting the bucket to full.
- **Thread-Safe In-Memory Storage**: Uses a granular locking hierarchy (registry lock for creation, per-bucket lock for evaluations) ensuring high concurrency.
- **Strict Validation**: Validates all inputs using Pydantic v2 (rejects non-positive numbers, empty keys, infinite floats, and requests where `cost > burst`).
- **Deterministic Testing**: Features dependency-injectable clock mechanics to test time-based refill behaviors with `FakeClock` without sleeping.
- **Ready for Production Integration**: Provides `/health` monitoring and standard Python logging.

---

## Project Structure

```text
d:/Mani project/
├── aidlc/
│   └── spaces/
│       └── default/
│           └── knowledge/
│               └── documents/
│                   └── intent.md
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application & HTTP routing
│   ├── limiter.py           # Core token-bucket algorithm & thread safety
│   └── schemas.py           # Pydantic request & response models
├── tests/
│   ├── test_limiter.py      # Unit tests with injected FakeClock & concurrency tests
│   └── test_api.py          # REST API integration & validation tests
├── docs/
│   ├── ANTIGRAVITY_BUILD_PROMPT.md  # Complete original build prompt
│   ├── PROJECT_SPEC.md      # Comprehensive technical specification
│   └── API.md               # API endpoint documentation & curl examples
├── README.md                # Project documentation & run guide
├── requirements.txt         # Runtime and test dependencies
├── .gitignore               # Ignored files for git
└── pyproject.toml           # Project packaging & pytest configuration
```

---

## Prerequisites

- **Python 3.9+** (tested on Python 3.13)
- `pip` package manager

---

## Setup and Installation

### 1. Create and Activate Virtual Environment (Recommended)

#### On Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

#### On Windows (Command Prompt):
```cmd
python -m venv .venv
.\.venv\Scripts\activate.bat
```

#### On Linux / macOS (Bash / Zsh):
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

Install all required runtime and development dependencies:

```bash
python -m pip install -r requirements.txt
```

---

## Application Startup

Start the FastAPI application with Uvicorn:

```bash
python -m uvicorn app.main:app --reload
```

The application will start on `http://127.0.0.1:8000`.

- Interactive Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Interactive ReDoc UI: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

---

## API Endpoints and Examples

### 1. Health Check

#### Request
```bash
curl -X GET "http://127.0.0.1:8000/health"
```

#### Response (HTTP 200 OK)
```json
{
  "status": "healthy",
  "service": "token-bucket-rate-limiter",
  "version": "1.0.0"
}
```

---

### 2. Rate Limit Evaluation

#### Request
```bash
curl -X POST "http://127.0.0.1:8000/v1/limit/check" \
     -H "Content-Type: application/json" \
     -d '{
       "key": "user-123",
       "rate_per_second": 2.0,
       "burst": 5,
       "cost": 1
     }'
```

#### Allowed Response (HTTP 200 OK)
```json
{
  "key": "user-123",
  "allowed": true,
  "remaining_tokens": 4.0,
  "retry_after_seconds": 0.0,
  "burst": 5,
  "rate_per_second": 2.0
}
```

#### Denied Response (HTTP 200 OK)
When available tokens are less than `cost`:
```json
{
  "key": "user-123",
  "allowed": false,
  "remaining_tokens": 0.0,
  "retry_after_seconds": 0.5,
  "burst": 5,
  "rate_per_second": 2.0
}
```

#### Malformed Input (HTTP 422 Unprocessable Entity)
When inputs violate constraints (e.g., `cost > burst`, `rate_per_second <= 0`):
```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body"],
      "msg": "Value error, cost (10) cannot exceed burst capacity (5)",
      "input": { ... }
    }
  ]
}
```

---

## Running the Automated Test Suite

Run the full pytest suite:

```bash
python -m pytest -q
```

Or for verbose output with all test cases listed:

```bash
python -m pytest -v
```

### Test Coverage Highlights
- **Algorithm verification**: Full capacity at start, token deduction, token capping at burst ceiling.
- **Refill over time**: Verifies exact mathematical refill using injected `FakeClock` without real-time sleeps.
- **Policy update resilience**: Verifies that updating rate or burst clamps tokens and never resets to full.
- **Retry-after calculation**: Confirms accurate `retry_after_seconds` based on missing tokens and rate.
- **Concurrency & Thread Safety**: Executes parallel worker threads hitting a shared key to verify zero state corruption and no token over-allocation.
- **Validation errors**: Enforces 422 responses on all invalid, negative, or out-of-range payloads.

---

## Algorithm Explanation

Unlike a **Fixed-Window Counter** which allows boundary bursts (e.g., 2x traffic at window transition), the **Token-Bucket Algorithm** models continuous flow:

1. **Bucket Capacity ($B$)**: Maximum number of tokens the bucket can hold at any instant.
2. **Refill Rate ($R$)**: Tokens continuously generated per unit time:
   $$\text{refilled} = \Delta t \times R$$
3. **Capacity Clamping**: Tokens accumulate up to the maximum burst:
   $$\text{tokens} = \min(B, \text{tokens} + \text{refilled})$$
4. **Consumption**: If $\text{tokens} \ge \text{cost}$, tokens are deducted and the request is permitted. Otherwise, the request is denied and no tokens are consumed.
5. **Backoff Calculation**: If denied, the exact delay before sufficient tokens will be available is calculated as:
   $$\text{retry\_after} = \frac{\text{cost} - \text{tokens}}{R}$$

---

## Known Limitations

1. **In-Memory Volatility**: State is maintained in process memory. If the server process restarts, all token buckets are re-initialized.
2. **Single-Process Scope**: State is stored in memory and is **not shared across multiple Uvicorn worker processes**. If running with multiple worker processes, configure an external shared store or run a single process.
3. **Memory Growth**: Buckets are retained in memory. If your use case generates hundreds of millions of ephemeral keys, an LRU or time-to-live (TTL) eviction cleanup policy should be introduced.
