# Observability & Monitoring Guide

IntentLead AI incorporates production observability across logging, health checking, database connectivity, and outreach campaign dispatch metrics.

---

## 1. Health Probes

The Intelligence API provides standard liveness and readiness HTTP endpoints for container orchestrators (Docker, Kubernetes, AWS ECS) and uptime monitors.

### `GET /health` or `GET /health/live`
- **Purpose**: Liveness probe. Verifies that the FastAPI process is responsive.
- **HTTP Status**: `200 OK`
- **Response**:
```json
{
  "status": "ok",
  "version": "0.2.0"
}
```

### `GET /health/ready`
- **Purpose**: Readiness probe. Tests end-to-end database connectivity and reports runtime posture.
- **HTTP Status**: `200 OK` (when healthy) or `503 Service Unavailable` (when database is down).
- **Response (Healthy)**:
```json
{
  "status": "ready",
  "database": "connected",
  "environment": "production",
  "provider": "scrapling",
  "outreach_mode": "dry-run"
}
```
- **Response (Degraded)**:
```json
{
  "status": "degraded",
  "database": "disconnected",
  "error": "connection to server at 'db' (172.18.0.2), port 5432 failed: Connection refused"
}
```

---

## 2. Request Tracing & Structured Logging

### Middleware Instrumentation
Every inbound HTTP request to the API is intercepted by the logging middleware in `app/main.py`:
1. **Timestamping**: Captures high-resolution start time (`time.perf_counter()`).
2. **Header Injection**: Appends `X-Response-Time: <ms>` header to the response for client-side latency tracking.
3. **Structured Log Event**: Emits a structured log line:
```
INFO: HTTP POST /api/campaigns -> 201 Created (142.35 ms) [IP: 192.168.1.10]
```

### Unhandled Exception Trapping
Any unhandled exception produces a structured traceback in logs and returns a safe, sanitized JSON payload without leaking internal stack traces:
```json
{
  "detail": "An internal server error occurred. This event has been logged."
}
```

---

## 3. Outreach & Deliverability Observability

### `GET /api/outreach/stats`
Returns live operational dispatch metrics:
```json
{
  "active_mailboxes": 4,
  "total_dispatched_today": 87,
  "hard_bounces": 1,
  "suppressed_recipients": 12,
  "throttled_leads": 0
}
```

### Webhook Telemetry: `POST /api/outreach/webhook/event`
Receives bounce and spam complaint notifications from ESPs (Amazon SES, SendGrid, Resend, or Google Workspace), atomically registering suppressed recipients and updating campaign message status.

---

## 4. Recommended Alert Triggers

| Metric / Alert | Threshold | Severity | Recommended Action |
| :--- | :--- | :--- | :--- |
| **Readiness Probe Failure** | `/health/ready` returns 503 for 2+ consecutive checks | Critical | Inspect PostgreSQL container / connection pool limits. |
| **API Response Latency** | `X-Response-Time` > 3000ms | Warning | Check website audit thread pool saturation or DNS lookup timeouts. |
| **Rate Limit Triggers** | HTTP 429 response rate > 10 / min | Warning | Investigate potential crawler or bot hitting `/api/campaigns`. |
| **Bounce Spike** | > 3 hard bounces in 1 hour | High | Pause active campaign; inspect email domain pre-flight gate. |
