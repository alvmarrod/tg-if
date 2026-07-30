# Code Quality Roadmap

**Source:** Full codebase review (Jul 2026)
**Branch:** `main..HEAD` — 33 files changed (+953/-341)

---

## Immediate Fixes (Bugs)

| # | Issue | File | Priority |
|---|-------|------|----------|
| CQ-01 | `service.stop()` called immediately on loop yield; signal handlers are dead code | `main.py:54` | Critical |
| CQ-02 | Exchange declared as `TOPIC` in rabbitmq.py but `publisher.py` uses `FANOUT` — topic routing broken | `publisher.py:56` | Critical |
| CQ-03 | Dead code after `return` (duplicate blocks that never execute) | `sqlite.py:164-169,176-179` | High |
| CQ-04 | `if not await storage.store(...)` checks `str` return as bool — verification never runs | `endpoint.py:84` | High |

---

## Type Safety

| # | Issue | Scope | Effort |
|---|-------|-------|--------|
| CQ-06 | 6 `# type: ignore` comments — fix underlying issues instead of suppressing | `main.py`, `health.py`, `consume.py`, `upload_routes.py` | Medium |
| CQ-07 | `dict[str, Any]` used extensively — replace with specific types / TypedDict | Across codebase | Large |
| CQ-08 | `Optional[X]` → `X \| None` migration not complete | Various files | Small |
| CQ-09 | `client._client` private attribute access defeats type checking | `endpoint.py` | Small |

---

## Error Handling

| # | Issue | Scope | Effort |
|---|-------|-------|--------|
| CQ-10 | `EventDispatcher.dispatch` has no try/except around publish — failure propagates uncaught | `event_dispatcher.py` | Medium |
| CQ-11 | Add dead-letter queue for messages exceeding max retries | `consumer.py` | Medium |
| CQ-12 | `ReceiverService.start()` crashes on single bot failure — degrade gracefully | `receiver_service.py` | Medium |
| CQ-13 | Consumer startup partial failure leaves prior consumers running | `receiver_service.py` | Small |
| CQ-14 | `_on_media_config_message` re-raises on validation failure, triggering retry loop for invalid messages | `media_config.py` | Small |

---

## Testing Gaps

| # | Area | Current | Target | Effort |
|---|------|---------|--------|--------|
| CQ-15 | `sqlite.py` (UploadRegistry) | 0 tests | Unit tests covering CRUD + edge cases | Medium |
| CQ-16 | `config.py` (ConfigLoader) | 0 tests | Env var loading, missing files, defaults | Medium |
| CQ-17 | `health.py` (health server) | 0 tests | `handle_health`, `handle_metrics`, server lifecycle | Medium |
| CQ-18 | `metrics_exporter.py` | 0 tests | Metric generation and Prometheus format | Small |
| CQ-19 | `receiver_service.py` | 0 tests | Start/stop/shutdown/restart with mocks | Large |
| CQ-20 | `main.py` | 0 tests | Config loading, service init | Medium |
| CQ-21 | `media_config.py` | 0 tests | Rule evaluation with precedence | Medium |
| CQ-22 | `chat_exporter.py` | 1 test file | Unit tests for serialization/export logic | Large |
| CQ-23 | Property-based tests for `_match_condition` | 0 | Hypothesis-based random input testing | Small |
| CQ-24 | Enforce `--cov=src --cov-report=term-missing` in pytest config | None | Coverage threshold e.g. 80% | Small |

---

## Pre-commit Hooks to Add

| # | Hook | Purpose | Effort |
|---|------|---------|--------|
| CQ-25 | `check-added-large-files` | Prevent accidentally committing media/binaries (>500KB) | Trivial |
| CQ-26 | `check-merge-conflict` | Detect unresolved merge markers | Trivial |
| CQ-27 | `check-json` / `check-yaml` | Validate config files are well-formed | Trivial |
| CQ-28 | `mixed-line-ending` | Normalize to LF | Trivial |
| CQ-29 | `trailing-whitespace` | Remove trailing whitespace | Trivial |
| CQ-30 | `check-toml` | Validate `pyproject.toml` | Trivial |
| CQ-31 | `debug-statements` | Catch `breakpoint()` / `pdb` left in code | Trivial |

---

## CI/CD

| # | Item | Effort |
|---|------|--------|
| CQ-32 | Add `pytest-cov` with coverage threshold to CI | Small |
| CQ-33 | Add `bandit` or `trivy` for Python security scanning | Small |
| CQ-34 | Add `pip-audit` or Dependabot for dependency vuln scanning | Small |
| CQ-35 | Add integration test stage in CI (Docker available in GA) | Medium |
| CQ-36 | Add release workflow (Docker image publish on tag) | Medium |
| CQ-37 | Cache `.venv` between CI runs more granularly | Small |
| CQ-38 | Matrix test across Python 3.12 / 3.13 | Small |

---

## Performance

| # | Issue | Detail | Effort |
|---|-------|--------|--------|
| CQ-39 | `Publisher.publish()` opens/closes channel per message | Use persistent channel instead | Medium ✅ |
| CQ-40 | `DiskStorage` uses sync I/O (`write_bytes`, `read_bytes`) in async context | Use `aiofiles` | Medium ✅ |
| CQ-41 | UploadRegistry SQLite ops not wrapped in `asyncio.to_thread` | Wrap all DB calls | Small ✅ |
| CQ-42 | Health monitor polls every 60s unconditionally | Add exponential backoff for healthy bots | Small ✅ |
| CQ-43 | Chat exporter file handles may leak on cancellation | Use context managers for file handles | Small ✅ |

---

## Architecture & Maintainability

| # | Issue | Effort |
|---|-------|--------|
| CQ-44 | Split `admin_commands.py` (1285 lines) into dispatch / formatting / business logic modules | Large |
| CQ-45 | Split `receiver_service.py` (465 lines) — extract wiring from lifecycle | Medium |
| CQ-46 | Add `docker-compose.yml` with RabbitMQ for local dev | Small |
| CQ-47 | Add OpenTelemetry tracing for end-to-end visibility | Large |
| CQ-48 | Sync version across `version.txt`, `pyproject.toml`, `main.py`; read from single source | Small ✅ |
| CQ-49 | Add LRU eviction or TTL to `DiskStorage._accesses` / `_last_access` dicts | Medium ✅ |
| CQ-50 | Document HTTP endpoint threat model (/health, /files/, /upload/ have no auth) | Small ✅ |
| CQ-51 | Add rate limiting to `/upload/` endpoint | Medium ✅ |
| CQ-52 | Fix session file race during rolling deployments | Medium ✅ |

---

## Overall Scores (from review)

| Dimension | Score | Key Issue |
|-----------|-------|-----------|
| Type Safety | 6/10 | Excessive `Any`, `# type: ignore` |
| Test Coverage | 7/10 | 398 tests, but infrastructure layer gaps |
| Error Handling | 7/10 | Great in consumer, poor in dispatcher |
| Logging | 8/10 | Structured, no tracing IDs |
| Code Organization | 9/10 | Excellent hexagonal architecture |
| Naming | 9/10 | Consistent and readable |
| Documentation | 8/10 | Sparse inline docstrings |
| Configuration | 8/10 | Version inconsistency |
| Consistency | 8/10 | Minor transitional inconsistencies |
| Maintainability | 8/10 | Some files too large |

## Overall: 7.8/10
