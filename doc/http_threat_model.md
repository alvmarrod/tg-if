# HTTP Endpoint Threat Model

## Scope

This document covers the HTTP API surface exposed by tg-if on the
`api_side_port` (default 8080). These endpoints are **unauthenticated**
and intended for use within a trusted network boundary (VPC, private
subnet, or localhost).

## Endpoints

| Path | Method | Purpose | Exposure |
|------|--------|---------|----------|
| `/health` | GET | Service + broker + client health status | Internal monitoring |
| `/metrics` | GET | Prometheus metrics export | Internal monitoring |
| `/files/{bot_id}/{file_unique_id}` | GET | Media file retrieval proxy | Subscriber access |
| `/upload/{bot_id}` | POST | Upload files for subsequent send via AMQP | Subscriber access |

## Threat Actors

| Actor | Capability |
|-------|-----------|
| **Network-adjacent attacker** | Can reach `api_side_port` if bound to `0.0.0.0` on a shared network |
| **Compromised subscriber** | Legitimate AMQP access; may probe HTTP endpoints |
| **Insider / misconfigured service** | May accidentally access or flood endpoints |

## Threats and Mitigations

### 1. Information Disclosure via `/health` and `/metrics`

**Threat:** An attacker enumerates bot names, broker connection status, or
internal metrics.

**Severity:** Low. These endpoints expose operational metadata but no
user data or credentials.

**Mitigation:**

- Bind the health/metrics server to `127.0.0.1` (localhost-only) if
  only local monitoring is needed.
- Place tg-if behind a reverse proxy (nginx, Caddy) with IP allowlists
  and/or HTTP Basic Auth for external access.
- Do not expose `api_side_port` directly to the public internet.

### 2. Unauthorized Media Retrieval via `/files/{bot_id}/{file_unique_id}`

**Threat:** An attacker who knows or guesses a `file_unique_id` can
download media cached by tg-if. File unique IDs are opaque hashes but
are **not treated as secrets** in the current design.

**Severity:** Medium. Cached media could contain sensitive content
(photos, documents, voice notes) depending on the bot's domain.

**Mitigation:**

- Do not expose `/files/` to the public internet.
- Place tg-if behind a reverse proxy with IP allowlists.
- For higher-security deployments, inject a shared secret or API key
  header via the reverse proxy layer (not currently enforced by tg-if).

### 3. Unrestricted File Upload to `/upload/{bot_id}`

**Threat:** An attacker uploads arbitrary files, consuming disk space
and potentially polluting the upload cache. Could be used for storage
abuse or as a step in a multi-stage attack.

**Severity:** Medium. Upload size is capped at `max_upload_size`
(default 2000 MB), but there is no rate limiting or authentication.

**Mitigation:**

- Rate limiting is applied per IP via the `aiohttp` middleware layer
  (see CQ-51).
- Place tg-if behind a reverse proxy with additional rate limiting
  (e.g., nginx `limit_req_zone`, Caddy `rate_limit`).
- Do not expose `/upload/` to the public internet.

### 4. Denial of Service

**Threat:** Any of the four endpoints can be flooded with requests,
exhausting connection pools, disk I/O (for `/files/` and `/upload/`),
or broker connections (for `/health`).

**Severity:** Medium–High depending on deployment context.

**Mitigation:**

- Rate limiting on `/upload/` (CQ-51) prevents unbounded disk writes.
- Reverse proxy connection limits and request queueing.
- The `/health` handler does not create new broker connections per
  request — it reads cached status — so flooding it has limited
  side effects.
- `/metrics` is a static text render with no I/O.

### 5. SSRF / Proxy Abuse via `/files/`

**Threat:** If file_id values happen to be URLs or the endpoint is used
as an open proxy, an attacker might relay requests.

**Severity:** Low. The `file_id` parameter is validated against the
registry; only registered Telegram file IDs trigger a download.
Arbitrary URLs are not accepted.

## Recommended Deployment Topology

```text
 [ Internet / Untrusted Network ]
           │
           ▼
   [ Reverse Proxy (nginx/Caddy) ]
     - TLS termination
     - IP allowlists
     - Rate limiting per path
     - Optional HTTP Basic Auth or header-based auth
           │
           ▼
   ┌─────────────────────────────────┐
   │  tg-if  (api_side_port)         │
   │  bind: 127.0.0.1:8080          │
   │  (localhost or private only)    │
   └─────────────────────────────────┘
```

## Unmitigated Risks

1. **No authentication on HTTP endpoints.** This is by design for a
   microservice within a trusted network. If public exposure is
   required, authentication must be added at the reverse proxy layer
   (not at tg-if's application layer).

2. **No request logging / audit trail.** Current logging is
   structured but does not include per-request access logs. For
   compliance environments, add access logging at the reverse proxy.

3. **No CSRF protection on `/upload/`.** Multipart form uploads are
   stateless; browser-based CSRF is not applicable, but automated
   scripts can POST without restriction if the endpoint is reachable.
