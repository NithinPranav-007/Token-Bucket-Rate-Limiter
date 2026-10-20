"""Integration tests for the Token-Bucket Rate Limiter REST API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.limiter import TokenBucketLimiter
from tests.test_limiter import FakeClock


@pytest.fixture
def client() -> TestClient:
    """Create a test client with a freshly reset limiter."""
    limiter = TokenBucketLimiter()
    app.state.limiter = limiter
    return TestClient(app)


@pytest.fixture
def fake_clock_client() -> tuple[TestClient, FakeClock]:
    """Create a test client with an injected FakeClock limiter."""
    clock = FakeClock(initial_time=500.0)
    limiter = TokenBucketLimiter(clock=clock)
    app.state.limiter = limiter
    return TestClient(app), clock


class TestHealthEndpoint:
    """Tests for GET /health endpoint."""

    def test_health_check_returns_200(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "token-bucket-rate-limiter"
        assert "version" in data

    def test_dashboard_endpoint_returns_200(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Token-Bucket Rate Limiter" in response.text

    def test_dashboard_fallback_when_template_missing(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.main as app_main
        from pathlib import Path
        monkeypatch.setattr(app_main, "INDEX_HTML", Path("non_existent_file.html"))
        response = client.get("/")
        assert response.status_code == 200
        assert "Frontend template not found" in response.text




class TestRateLimitEndpoint:
    """Tests for POST /v1/limit/check endpoint."""

    def test_first_request_allowed_with_defaults(self, client: TestClient) -> None:
        payload = {
            "key": "user-123",
            "rate_per_second": 2.0,
            "burst": 5,
            "cost": 1,
        }
        response = client.post("/v1/limit/check", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["key"] == "user-123"
        assert data["allowed"] is True
        assert data["remaining_tokens"] == 4.0
        assert data["retry_after_seconds"] == 0.0
        assert data["burst"] == 5
        assert data["rate_per_second"] == 2.0

    def test_cost_defaults_to_one(self, client: TestClient) -> None:
        payload = {
            "key": "user-default-cost",
            "rate_per_second": 1.0,
            "burst": 3,
            # cost omitted
        }
        response = client.post("/v1/limit/check", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["allowed"] is True
        assert data["remaining_tokens"] == 2.0  # 3 - 1 default

    def test_rate_limit_exceeded_denied_with_200(self, client: TestClient) -> None:
        payload = {
            "key": "user-deny-test",
            "rate_per_second": 2.0,
            "burst": 2,
            "cost": 2,
        }
        # Consume all 2 tokens
        res1 = client.post("/v1/limit/check", json=payload)
        assert res1.status_code == 200
        assert res1.json()["allowed"] is True
        assert res1.json()["remaining_tokens"] == 0.0

        # Next request must be denied with HTTP 200 (rate limit decision, not error)
        res2 = client.post("/v1/limit/check", json=payload)
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["allowed"] is False
        assert 0.0 <= data2["remaining_tokens"] < payload["cost"]
        assert 0.0 < data2["retry_after_seconds"] <= 1.0

    def test_time_advancement_refills_via_api(
        self, fake_clock_client: tuple[TestClient, FakeClock]
    ) -> None:
        client, clock = fake_clock_client
        payload = {
            "key": "user-time-refill",
            "rate_per_second": 4.0,
            "burst": 10,
            "cost": 10,
        }
        # Drain all tokens
        res1 = client.post("/v1/limit/check", json=payload)
        assert res1.json()["remaining_tokens"] == 0.0

        # Advance fake clock by 0.5s -> 0.5 * 4 = 2 tokens refilled
        clock.advance(0.5)

        # Check request with cost 2
        res2 = client.post(
            "/v1/limit/check",
            json={
                "key": "user-time-refill",
                "rate_per_second": 4.0,
                "burst": 10,
                "cost": 2,
            },
        )
        assert res2.status_code == 200
        assert res2.json()["allowed"] is True
        assert res2.json()["remaining_tokens"] == 0.0


class TestValidationErrors:
    """Tests ensuring malformed requests produce HTTP 422 Unprocessable Entity."""

    def test_empty_key_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/v1/limit/check",
            json={"key": "", "rate_per_second": 1.0, "burst": 5, "cost": 1},
        )
        assert response.status_code == 422

    def test_whitespace_key_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/v1/limit/check",
            json={"key": "   ", "rate_per_second": 1.0, "burst": 5, "cost": 1},
        )
        assert response.status_code == 422

    def test_zero_rate_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/v1/limit/check",
            json={"key": "test", "rate_per_second": 0.0, "burst": 5, "cost": 1},
        )
        assert response.status_code == 422

    def test_negative_rate_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/v1/limit/check",
            json={"key": "test", "rate_per_second": -1.5, "burst": 5, "cost": 1},
        )
        assert response.status_code == 422

    def test_zero_burst_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/v1/limit/check",
            json={"key": "test", "rate_per_second": 2.0, "burst": 0, "cost": 1},
        )
        assert response.status_code == 422

    def test_negative_burst_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/v1/limit/check",
            json={"key": "test", "rate_per_second": 2.0, "burst": -5, "cost": 1},
        )
        assert response.status_code == 422

    def test_zero_cost_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/v1/limit/check",
            json={"key": "test", "rate_per_second": 2.0, "burst": 5, "cost": 0},
        )
        assert response.status_code == 422

    def test_negative_cost_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/v1/limit/check",
            json={"key": "test", "rate_per_second": 2.0, "burst": 5, "cost": -2},
        )
        assert response.status_code == 422

    def test_cost_exceeding_burst_rejected(self, client: TestClient) -> None:
        """Cost cannot exceed burst capacity."""
        response = client.post(
            "/v1/limit/check",
            json={"key": "test", "rate_per_second": 2.0, "burst": 5, "cost": 6},
        )
        assert response.status_code == 422
        body = response.json()
        assert "detail" in body

    def test_missing_required_fields_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/v1/limit/check",
            json={"key": "test"},
        )
        assert response.status_code == 422

    def test_invalid_types_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/v1/limit/check",
            json={
                "key": 12345,
                "rate_per_second": "not-a-number",
                "burst": 5,
            },
        )
        assert response.status_code == 422

    def test_nan_or_inf_rate_rejected(self, client: TestClient) -> None:
        """Rate cannot be infinity or NaN."""
        # Using schema directly or payload to test validator
        from app.schemas import RateLimitRequest

        with pytest.raises(Exception):
            RateLimitRequest(key="test", rate_per_second=float("inf"), burst=5, cost=1)

        with pytest.raises(Exception):
            RateLimitRequest(key="test", rate_per_second=float("nan"), burst=5, cost=1)


class TestAppArchitectureAndLifecycle:
    """Tests for lifespan context manager, dependency injection, and OpenAPI."""

    def test_lifespan_event_triggers(self) -> None:
        """Context manager with TestClient triggers startup lifespan."""
        with TestClient(app) as test_client:
            res = test_client.get("/health")
            assert res.status_code == 200

    def test_default_limiter_dependency_injection(self) -> None:
        """When app.state.limiter is cleared, fallback to global limiter_instance."""
        if hasattr(app.state, "limiter"):
            delattr(app.state, "limiter")
        raw_client = TestClient(app)
        res = raw_client.post(
            "/v1/limit/check",
            json={"key": "default-dep", "rate_per_second": 1.0, "burst": 5, "cost": 1},
        )
        assert res.status_code == 200
        assert res.json()["allowed"] is True

    def test_openapi_schema_endpoint(self, client: TestClient) -> None:
        """OpenAPI JSON spec is generated correctly."""
        res = client.get("/openapi.json")
        assert res.status_code == 200
        data = res.json()
        assert data["info"]["title"] == "Token-Bucket Rate Limiter API"
        assert "/health" in data["paths"]
        assert "/v1/limit/check" in data["paths"]

    def test_method_not_allowed(self, client: TestClient) -> None:
        """GET on POST-only endpoint returns 405 Method Not Allowed."""
        res = client.get("/v1/limit/check")
        assert res.status_code == 405

    def test_not_found_endpoint(self, client: TestClient) -> None:
        """Nonexistent route returns 404 Not Found."""
        res = client.get("/v1/nonexistent")
        assert res.status_code == 404


class TestLimiterTelemetryEndpoint:
    """Tests for GET /v1/limiter/status and DELETE /v1/limiter/reset."""

    def test_get_limiter_status_endpoint(self, client: TestClient) -> None:
        # Trigger an allowed and a denied request
        client.post(
            "/v1/limit/check",
            json={"key": "telemetry-user", "rate_per_second": 1.0, "burst": 5, "cost": 1},
        )
        res = client.get("/v1/limiter/status")
        assert res.status_code == 200
        data = res.json()
        assert data["total_requests"] >= 1
        assert data["total_allowed"] >= 1
        assert data["total_keys"] >= 1
        assert any(b["key"] == "telemetry-user" for b in data["buckets"])

    def test_reset_limiter_endpoint(self, client: TestClient) -> None:
        client.post(
            "/v1/limit/check",
            json={"key": "to-reset", "rate_per_second": 1.0, "burst": 5, "cost": 1},
        )
        res_del = client.delete("/v1/limiter/reset")
        assert res_del.status_code == 200
        assert "reset" in res_del.json()["message"]

        res_status = client.get("/v1/limiter/status")
        assert res_status.json()["total_keys"] == 0


