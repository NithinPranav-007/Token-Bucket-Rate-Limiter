# API Reference: Token-Bucket Rate Limiter REST API

The Token-Bucket Rate Limiter exposes an HTTP REST API for checking service health and evaluating per-key token-bucket limits.

- **Base URL**: `http://127.0.0.1:8000`
- **Interactive OpenAPI Documentation**: `http://127.0.0.1:8000/docs`
- **ReDoc Documentation**: `http://127.0.0.1:8000/redoc`

---

## Endpoints Summary

| Method | Endpoint | Description | Status Codes |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | Service health status check | `200` |
| `POST` | `/v1/limit/check` | Evaluate and consume tokens for a key | `200`, `422` |

---

## 1. Health Check

### `GET /health`
Returns the operational health and version information of the running service.

#### Request
No parameters or headers required.

#### Response: 200 OK
```json
{
  "status": "healthy",
  "service": "token-bucket-rate-limiter",
  "version": "1.0.0"
}
```

#### Curl Example
```bash
curl -X GET "http://127.0.0.1:8000/health" \
     -H "Accept: application/json"
```

---

## 2. Check and Consume Rate Limit

### `POST /v1/limit/check`
Evaluates whether a request with a specified token cost is permitted for a given key, refills tokens based on elapsed monotonic time, and deducts the cost if allowed.

#### Request Headers
- `Content-Type: application/json`
- `Accept: application/json`

#### Request Schema

| Field | Type | Required | Default | Validation Rules | Description |
| :--- | :--- | :---: | :---: | :--- | :--- |
| `key` | string | **Yes** | — | Non-empty, non-whitespace string | Unique client or entity identifier (e.g. user ID, IP address, API key). |
| `rate_per_second` | float | **Yes** | — | Finite float > 0.0 | Token refill speed in tokens added per second. |
| `burst` | integer | **Yes** | — | Positive integer > 0 | Maximum token burst capacity (bucket ceiling). |
| `cost` | integer | No | `1` | Positive integer, `1 <= cost <= burst` | Tokens requested for this specific operation. |

#### Example Request Body
```json
{
  "key": "user-123",
  "rate_per_second": 2.0,
  "burst": 5,
  "cost": 1
}
```

---

### Response Details

#### 1. Rate Limit Allowed (`200 OK`)
Returned when sufficient tokens exist to satisfy the requested cost. Tokens are deducted.

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

#### 2. Rate Limit Denied (`200 OK`)
Returned when remaining tokens are strictly less than `cost`. **No tokens are deducted.** A non-negative `retry_after_seconds` is provided indicating when sufficient tokens will have accumulated.

```json
{
  "key": "user-123",
  "allowed": false,
  "remaining_tokens": 0.5,
  "retry_after_seconds": 0.75,
  "burst": 5,
  "rate_per_second": 2.0
}
```

> **Note on HTTP 200**: In this design, being denied due to rate limits is a successful policy decision, not an application failure or invalid request. Upstream clients inspect the `allowed` boolean and `retry_after_seconds`.

#### 3. Validation Error (`422 Unprocessable Entity`)
Returned when the request payload is malformed or violates constraints (e.g. `cost > burst`, `burst <= 0`, empty `key`, infinite `rate_per_second`).

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body"],
      "msg": "Value error, cost (10) cannot exceed burst capacity (5)",
      "input": {
        "key": "user-123",
        "rate_per_second": 2.0,
        "burst": 5,
        "cost": 10
      }
    }
  ]
}
```

---

## Practical Curl Examples

### Example 1: Basic Allowed Request
```bash
curl -X POST "http://127.0.0.1:8000/v1/limit/check" \
     -H "Content-Type: application/json" \
     -d '{
       "key": "client-mobile-app",
       "rate_per_second": 5.0,
       "burst": 10,
       "cost": 1
     }'
```

### Example 2: High-Cost Request
```bash
curl -X POST "http://127.0.0.1:8000/v1/limit/check" \
     -H "Content-Type: application/json" \
     -d '{
       "key": "batch-export-job",
       "rate_per_second": 1.0,
       "burst": 20,
       "cost": 15
     }'
```

### Example 3: Simulating Depletion (PowerShell)
```powershell
1..6 | ForEach-Object {
    Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/limit/check" `
                      -Method Post `
                      -ContentType "application/json" `
                      -Body '{"key":"demo-user","rate_per_second":1.0,"burst":5,"cost":1}'
}
```
The first 5 calls return `allowed: True` with decreasing remaining tokens; the 6th call returns `allowed: False` with `retry_after_seconds: 1.0`.
