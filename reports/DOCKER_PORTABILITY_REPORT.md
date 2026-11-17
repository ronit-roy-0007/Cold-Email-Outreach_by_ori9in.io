# IntentLead AI — Docker Portability & Multi-Platform Deployment Report

**Report Date:** 2026-11-17  
**Auditor & Architect:** Principal DevOps Engineer & System Architect  
**Status:** DOCKER PORTABILITY VERIFIED ACROSS ALL TARGET ENVIRONMENTS  

---

## 1. Executive Summary

This report evaluates the containerization, orchestration, portability, and deployment architecture of **IntentLead AI** across the four officially supported deployment operating environments:
1. Windows 10/11 with Docker Desktop (WSL2 backend)
2. Linux (Ubuntu, Debian, Fedora, Arch) with Docker Engine and Docker Compose v2
3. macOS (Apple Silicon arm64 & Intel x86_64) with Docker Desktop
4. Ubuntu 22.04 / 24.04 LTS VPS Deployments

The containerization stack adheres to production Docker best practices: unprivileged user execution, automated multi-stage healthchecks, internal network isolation, log rotation policies, and fail-closed migration hooks.

---

## 2. Container Topology & Service Architecture

```text
+----------------------------------------------------------------------------------+
|                            DOCKER COMPOSE TOPOLOGY                               |
|                                                                                  |
|   [Host Port 8000 (127.0.0.1)]                                                   |
|                │                                                                 |
|                ▼                                                                 |
|   ┌───────────────────────────┐      ┌───────────────────────────┐               |
|   │     intentlead-api        │      │ intentlead-telegram-poller│               |
|   │ (FastAPI, Python 3.12)    │      │  (Long-polling worker)    │               |
|   │ UID: 10001 (appuser)      │      │ UID: 10001 (appuser)      │               |
|   │ Health: /health/ready     │      │                           │               |
|   └─────────────┬─────────────┘      └─────────────┬─────────────┘               |
|                 │                                  │                             |
|                 └──────────────────┬───────────────┘                             |
|                                    │                                             |
|                     [Internal Docker Bridge Network]                             |
|                                    │                                             |
|                 ┌──────────────────┴───────────────┐                             |
|                 │                                  │                             |
|                 ▼                                  ▼                             |
|   ┌───────────────────────────┐      ┌───────────────────────────┐               |
|   │      intentlead-db        │      │    intentlead-redis       │               |
|   │   (PostgreSQL 16 Alpine)  │      │     (Redis 7 Alpine)      │               |
|   │   Volume: postgres_data   │      │   Volume: redis_data      │               |
|   │   Health: pg_isready      │      │   Health: redis-cli ping  │               |
|   │   NO HOST PORT EXPOSURE   │      │   NO HOST PORT EXPOSURE   │               |
|   └───────────────────────────┘      └───────────────────────────┘               |
+----------------------------------------------------------------------------------+
```

---

## 3. Platform Compatibility Matrix

| Environment | Supported Architecture | Runtime Prerequisites | Verification Status |
|---|---|---|---|
| **Windows 10/11** | `x86_64` (amd64) | Docker Desktop with WSL2 backend enabled | Verified |
| **Linux (Ubuntu/Debian)** | `x86_64`, `aarch64` | Docker Engine >= 24.0, Docker Compose v2 | Verified |
| **macOS (Apple Silicon)** | `arm64` (M1/M2/M3/M4) | Docker Desktop for Mac | Verified |
| **macOS (Intel)** | `x86_64` | Docker Desktop for Mac | Verified |
| **Ubuntu VPS** | `x86_64`, `aarch64` | Ubuntu 22.04/24.04 LTS, Docker Compose | Verified |

---

## 4. Hardened Security & Operational Standards

1. **Non-Root User Enforcement:**
   Containers run as user `appuser` with explicit UID `10001` and primary group `appuser`. The root filesystem is protected, preventing privilege escalation.
2. **Network Isolation:**
   In production (`docker-compose.prod.yml`), PostgreSQL (`5432`) and Redis (`6379`) publish zero ports to the host network. They communicate exclusively over Docker's internal overlay bridge network.
3. **Fail-Closed Database Migrations:**
   `docker-entrypoint.sh` executes an active 30-second connection poll via SQLAlchemy pre-ping, followed by `alembic upgrade head || exit 1`. If migrations fail, the container halts immediately to avoid serving requests against mismatched schemas.
4. **Healthcheck Probes & Dependency Ordering:**
   - PostgreSQL: `pg_isready -U intentlead -d intentlead` (Interval: 5s, Retries: 5).
   - Redis: `redis-cli ping` (Interval: 5s, Retries: 5).
   - API Service: `http://localhost:8000/health/ready` verifying end-to-end database connectivity.
   - `telegram-poller` and `worker` depend on `api: service_healthy` before initiating startup.
5. **Log Rotation Policy:**
   Every container enforces the `json-file` logging driver with `max-size: 10m` and `max-file: 3` to eliminate disk exhaustion.
6. **Self-Contained Portable Dependencies:**
   Zero external C-extensions for password hashing (pure-Python PBKDF2-HMAC-SHA256 from standard library) ensures seamless multi-arch builds without compilation failures.

---
*Report certified by Principal DevOps Engineer & System Architect.*
