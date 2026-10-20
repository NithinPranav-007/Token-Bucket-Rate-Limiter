# ANTIGRAVITY MASTER PROMPT — COMPLETE TOKEN-BUCKET RATE LIMITER PROJECT

Act as a senior Python backend engineer and autonomous software development agent. Your task is to **build the complete, working Token-Bucket Rate Limiter project directly inside the current project directory**.

Do not merely explain, plan, demonstrate, or generate a ZIP file. You must create the actual source files, configuration files, Markdown documents, and automated tests in the project directory, execute the application and tests, and fix any issues you discover.

## 1. Inspect the workspace first

- Identify the current project root and inspect its existing files.
- Work directly inside that directory.
- Preserve unrelated existing files and configurations.
- Do not create the project in a different directory or place files outside the project root.
- Do not stop after producing a plan, report, or scaffold. Continue through implementation and verification.

## 2. Project objective

Build a lightweight **Token-Bucket Rate Limiter REST API** using Python.

The service must decide whether a request should be allowed or denied according to a configurable token refill rate, burst capacity, and requested token cost.

Use the token-bucket algorithm, not a fixed-window counter.

### Technology stack

- Python 3
- FastAPI
- Pydantic
- pytest
- In-memory, thread-safe bucket storage
- Standard Python logging

No Docker, external database server, Redis, cloud infrastructure, authentication, frontend, or external services are required.

## 3. Implement the API

### `GET /health`

Return HTTP 200 with a JSON health status.

### `POST /v1/limit/check`

Accept this JSON request:

```json
{
  "key": "user-123",
  "rate_per_second": 2.0,
  "burst": 5,
  "cost": 1
}
```

Return a response in this format:

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

Implement the following validation:
- `key` must be a non-empty string.
- `rate_per_second` must be finite and greater than zero.
- `burst` must be a positive integer.
- `cost` must be a positive integer, defaults to 1, and cannot exceed the burst capacity.
- Reject malformed requests with HTTP 422 and a clear validation response.

Valid allow/deny decisions must return HTTP 200. Denial is a rate-limit decision, not a validation error.

## 4. Implement the actual token-bucket algorithm

Create a modular implementation with these behaviors:

1. Initialize a newly encountered key with a full token bucket.
2. Refill tokens using elapsed monotonic time multiplied by the configured refill rate.
3. Never let available tokens exceed the burst capacity.
4. Allow a request when sufficient tokens are available, deducting its cost.
5. Deny a request when insufficient tokens are available, without deducting tokens.
6. Calculate the retry time as missing tokens divided by the configured refill rate.
7. Maintain independent bucket states for different keys.
8. Protect bucket-state updates with appropriate thread synchronization.
9. Inject the clock so tests can simulate elapsed time deterministically without sleeping.
10. Handle changes to a key's rate or burst policy without unexpectedly resetting its bucket to full. Clamp existing tokens to the new capacity and apply the new refill rate.
11. Return consistent, non-negative remaining-token and retry-time values.
12. Document that in-memory state is lost when the service restarts and is not shared across multiple worker processes.

Use clear types, meaningful names, sensible error handling, and separation between business logic and HTTP handlers.

## 5. Create the complete project directly in the project directory

Create and populate these files:

```text
project-root/
├── aidlc/
│   └── spaces/
│       └── default/
│           └── knowledge/
│               └── documents/
│                   └── intent.md
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── limiter.py
│   └── schemas.py
├── tests/
│   ├── test_limiter.py
│   └── test_api.py
├── docs/
│   ├── ANTIGRAVITY_BUILD_PROMPT.md
│   ├── PROJECT_SPEC.md
│   └── API.md
├── README.md
├── requirements.txt
├── .gitignore
└── pyproject.toml
```

You may make small structural adjustments if necessary, but retain the same project scope and documentation deliverables.

**Important:** These files must contain their actual, complete content. Do not create empty placeholder files, TODO-only implementations, or documentation that claims functionality which does not exist.

### `intent.md`

Create the intent document at exactly:

`aidlc/spaces/default/knowledge/documents/intent.md`

Fill in the template's sections for:
- What to build
- Who uses it
- Must-have behaviors
- Out of scope

Preserve the remaining supplied template content and run configuration wherever the original template is available. If it is not present, reconstruct the relevant configuration from the requirements below.

### `docs/ANTIGRAVITY_BUILD_PROMPT.md`

Save this complete master prompt into the project itself at:

`docs/ANTIGRAVITY_BUILD_PROMPT.md`

The file must contain the actual build instructions, project objective, API contract, algorithm requirements, documentation requirements, tests, and completion criteria.

Do not save only a summary of this prompt.

### `docs/PROJECT_SPEC.md`

Document the architecture, token-bucket algorithm, state management, policy changes, assumptions, error handling, limitations, and out-of-scope features.

### `docs/API.md`

Document each endpoint, request and response schemas, HTTP status codes, validation behavior, and practical curl examples.

### `README.md`

Include:
- Project overview and features
- Prerequisites
- Virtual-environment creation and activation for Windows and Unix-like systems
- Dependency installation
- Application startup
- Endpoint documentation and curl examples
- Running the test suite
- Project structure
- Algorithm explanation
- Known limitations

Ensure the instructions work with the actual files you create.

## 6. Automated testing

Create comprehensive but focused pytest tests.

Test at least:
- New buckets begin at full capacity.
- Requests are allowed while sufficient tokens remain.
- Requests are denied when insufficient tokens remain.
- Burst capacity is enforced.
- Tokens refill correctly as time advances.
- Retry-time calculations are correct.
- Denied requests do not deduct additional tokens.
- Different keys maintain independent state.
- Policy changes update existing buckets correctly.
- Invalid inputs are rejected.
- The health endpoint returns the expected status.
- The rate-limit endpoint returns valid allow and deny responses.
- Concurrent accesses do not corrupt bucket state, where practical.

Use an injected fake clock for time-dependent algorithm tests. Avoid arbitrary real-time sleeps and external dependencies.

Run the entire pytest suite, inspect any failures, and fix them before completion.

## 7. Project configuration and execution

Make sure the following commands work from the project root, adapting only when necessary to the final configuration.

Install dependencies:

`python -m pip install -r requirements.txt`

Start the application:

`python -m uvicorn app.main:app --reload`

Run tests:

`python -m pytest -q`

Use sensible dependency versions and ensure the application runs with Python 3. Do not require Docker or a separately installed database.

## 8. Scope restrictions

Build only this one service and its supporting files.

Do not add:
- Frontend or dashboard
- User accounts or authentication
- Redis or distributed rate limiting
- Microservices
- Database servers
- Cloud deployment or Terraform execution
- Payment systems
- API gateway integrations
- Unrelated functionality

Choose reasonable defaults for non-blocking decisions. Record important assumptions in the project documentation rather than repeatedly asking for confirmation.

## 9. Final implementation and verification

Execute these tasks in order:

1. Inspect the current workspace.
2. Create or update all required files inside the current project root.
3. Implement the API and token-bucket business logic.
4. Write all required Markdown documentation.
5. Write the automated tests.
6. Install missing dependencies when the environment permits.
7. Execute the complete test suite.
8. Start the service and verify its health and rate-limit endpoints when possible.
9. Fix any discovered implementation, configuration, documentation, or test issues.
10. Verify that every expected file exists in the project directory and contains its intended content.
11. Ensure the README commands match the actual implementation.

If an environment limitation prevents a verification step, state exactly what could not be verified. Never invent successful test results.

## FINAL RULE

**Build everything directly in the existing project directory.** The source code, tests, Markdown documents, filled intent document, and this saved master prompt must all be physically present in the workspace.

Do not respond with only code snippets, a plan, a checklist, a ZIP attachment, or instructions for me to implement it manually.

Start by inspecting the workspace, then complete the implementation autonomously and report the files created, commands used, test results, and any remaining limitations.
