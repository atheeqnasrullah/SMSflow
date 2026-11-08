# SMSFlow – System Architecture

> **One Platform. Every Customer. Smarter Communication.**
>
> A multi-tenant SaaS platform for bulk SMS, OTP, transactional notifications and scheduled campaigns for Sri Lankan businesses.

| Item | Value |
| --- | --- |
| Document | Architecture specification |
| Version | 1.0 (initial design) |
| Status | Draft – pre-implementation |
| Scope | Web app, backend API, messaging engine, billing, developer API, super-admin |

---

## Table of Contents

1. [Architecture Goals and Principles](#1-architecture-goals-and-principles)
2. [High-Level System Context](#2-high-level-system-context)
3. [Container / Component Architecture](#3-container--component-architecture)
4. [Technology Stack](#4-technology-stack)
5. [Backend Module Design](#5-backend-module-design)
6. [Multi-Tenancy Design](#6-multi-tenancy-design)
7. [Data Model](#7-data-model)
8. [Messaging Engine](#8-messaging-engine)
9. [SMS Provider Adapter Layer](#9-sms-provider-adapter-layer)
10. [Wallet, Billing and Payments](#10-wallet-billing-and-payments)
11. [Developer API and Webhooks](#11-developer-api-and-webhooks)
12. [Authentication and Authorization](#12-authentication-and-authorization)
13. [Security Architecture](#13-security-architecture)
14. [Frontend Architecture](#14-frontend-architecture)
15. [Localization and SMS Encoding](#15-localization-and-sms-encoding)
16. [Observability](#16-observability)
17. [Deployment Architecture](#17-deployment-architecture)
18. [Scalability and Reliability](#18-scalability-and-reliability)
19. [Repository Structure](#19-repository-structure)
20. [Testing Strategy](#20-testing-strategy)
21. [Implementation Roadmap](#21-implementation-roadmap)
22. [Future Extensions](#22-future-extensions)
23. [Architecture Decision Records](#23-architecture-decision-records)

---

## 1. Architecture Goals and Principles

### 1.1 Goals

| Goal | How the architecture addresses it |
| --- | --- |
| **Tenant isolation** | `tenant_id` on every business table + PostgreSQL Row-Level Security (RLS) as a second line of defence |
| **Reliable delivery** | Asynchronous queue (Redis + Celery), idempotent jobs, retries with backoff, dead-letter handling |
| **Financial accuracy** | Append-only wallet ledger, reserve → capture → refund flow, idempotent payment processing |
| **Provider independence** | `SmsProvider` interface; demo and real providers are interchangeable adapters |
| **Developer friendliness** | Versioned REST API (`/api/v1`), API keys, signed webhooks, OpenAPI docs |
| **Extensibility** | Channel-agnostic message model so WhatsApp/email can be added later |
| **Operability** | Containerised services, structured logs, Sentry, metrics, health checks |

### 1.2 Principles

1. **Modular monolith first.** One FastAPI codebase organised by domain modules, deployed as an API service plus worker services. Split into microservices only when a module has a proven, independent scaling need.
2. **The API never talks to SMS providers directly.** All sending goes through the queue so HTTP requests stay fast and failures are retried.
3. **Money is never mutated, only appended.** Balances are derived from (and reconciled against) ledger entries.
4. **Every external callback is untrusted** until its signature/source is verified (payment notifications, delivery reports).
5. **Idempotency everywhere** a retry can happen: API sends, payment notifications, DLR processing, Celery tasks.
6. **Demo is a first-class mode, clearly labelled.** Demo messages and campaigns are flagged end-to-end and never mixed with real billing.

---

## 2. High-Level System Context

```mermaid
flowchart LR
    subgraph Users
        BU[Business Users<br/>Owner / Admin / Manager / Operator / Viewer]
        DEV[External Applications<br/>e-commerce, clinics, LMS]
        SA[Super Admin<br/>SMSFlow staff]
        PUB[Public Visitors]
    end

    LN[(SMSFlow Platform)]

    subgraph External Services
        SMSP[SMS Providers<br/>Demo / SMSlenz / Text.lk / Twilio / Sinch]
        PAY[Payment Gateway<br/>PayHere]
        MAIL[Email Service<br/>SMTP / SES / Resend]
        SENTRY[Sentry]
    end

    MNO[Sri Lankan Mobile Networks<br/>Dialog / Mobitel / Hutch / Airtel]
    END[End Customers' Phones]

    PUB -->|Landing, pricing, docs| LN
    BU -->|Dashboard| LN
    SA -->|Admin console| LN
    DEV -->|REST API + API key| LN
    LN -->|Webhooks| DEV

    LN -->|Send SMS| SMSP
    SMSP -->|Delivery reports| LN
    SMSP --> MNO --> END

    BU -->|Checkout| PAY
    PAY -->|Payment notification| LN
    LN --> MAIL
    LN --> SENTRY
```

---

## 3. Container / Component Architecture

```mermaid
flowchart TB
    subgraph Edge
        NGINX[Nginx<br/>TLS termination, reverse proxy,<br/>rate limiting, gzip]
    end

    subgraph Frontend
        WEB[Next.js App<br/>Public site + Dashboard + Admin<br/>TypeScript + Tailwind]
    end

    subgraph Backend
        API[FastAPI API Service<br/>REST /api/v1, auth, validation,<br/>business logic]
        BEAT[Celery Beat<br/>Scheduler]
        WSEND[Celery Workers: sms.send]
        WCAMP[Celery Workers: campaigns.expand]
        WHOOK[Celery Workers: webhooks / dlr / email]
    end

    subgraph Data
        PG[(PostgreSQL<br/>primary data + RLS)]
        REDIS[(Redis<br/>broker, cache,<br/>rate-limit counters)]
        OBJ[(Object Storage<br/>CSV imports, exports,<br/>invoices)]
    end

    subgraph Providers
        ADAPT[Provider Adapter Layer]
        DEMO[Demo SMS Gateway]
        REAL[Real SMS Provider APIs]
    end

    NGINX --> WEB
    NGINX --> API
    WEB -->|HTTPS JSON| API

    API --> PG
    API --> REDIS
    API --> OBJ
    API -->|enqueue| REDIS

    BEAT -->|scheduled campaigns,<br/>DLR polling, reconciliation| REDIS
    REDIS --> WCAMP
    REDIS --> WSEND
    REDIS --> WHOOK

    WCAMP --> PG
    WSEND --> PG
    WSEND --> ADAPT
    ADAPT --> DEMO
    ADAPT --> REAL
    WHOOK --> PG

    REAL -->|DLR callback| NGINX
```

### 3.1 Deployable units

| Unit | Responsibility | Scaling |
| --- | --- | --- |
| `web` | Next.js SSR/static pages, dashboard UI | Horizontal, stateless |
| `api` | FastAPI (Uvicorn/Gunicorn), all REST endpoints, callbacks | Horizontal, stateless |
| `worker-send` | Sends individual messages through provider adapters | Horizontal; concurrency tuned per provider rate limit |
| `worker-default` | Campaign expansion, imports/exports, DLR processing, webhooks, email | Horizontal |
| `beat` | Celery Beat — triggers due campaigns and periodic jobs | **Exactly one instance** |
| `postgres` | System of record | Vertical first, then read replicas |
| `redis` | Broker + cache | Vertical; managed Redis in production |
| `nginx` | Reverse proxy, TLS | Single/pair behind cloud LB |

---

## 4. Technology Stack

| Layer | Technology | Purpose |
| --- | --- | --- |
| Frontend | **Next.js (App Router)** + **TypeScript** | Public website, dashboard, admin console |
| Styling | **Tailwind CSS** (+ shadcn/ui components) | Responsive UI |
| Frontend data | TanStack Query, React Hook Form, Zod | Server state, forms, validation |
| Charts | Recharts | Delivery analytics |
| i18n | next-intl | English / Sinhala / Tamil UI |
| Backend | **FastAPI** (Python 3.12) | REST API, OpenAPI docs |
| Validation | Pydantic v2 | Request/response schemas, settings |
| ORM | **SQLAlchemy 2.x** (async) | Data access |
| Migrations | **Alembic** | Schema versioning (including RLS policies) |
| Database | **PostgreSQL 16** | Primary store, RLS, JSONB, partitioning |
| Queue / Cache | **Redis 7** | Celery broker, caching, rate-limit counters |
| Background jobs | **Celery** + Celery Beat | Sending, scheduling, webhooks, reconciliation |
| HTTP client | **HTTPX** | Provider + webhook calls (timeouts, retries) |
| Auth | **JWT** (access + rotating refresh), Argon2 password hashing | Authentication |
| Phone numbers | `phonenumbers` | E.164 normalisation, Sri Lankan validation |
| Files | `openpyxl`, `csv` | Contact import/export |
| Containers | **Docker** + Docker Compose | Local + production packaging |
| Proxy | **Nginx** | TLS, routing, request size limits |
| CI/CD | **GitHub Actions** | Lint, test, build, deploy |
| Monitoring | **Sentry**, Prometheus/Grafana (optional), Flower | Errors, metrics, queue visibility |

---

## 5. Backend Module Design

The backend is a **modular monolith**. Each domain module owns its router, schemas, service layer and models. Modules communicate through service functions (not through each other's tables) and through domain events placed on the queue.

```mermaid
flowchart LR
    AUTH[auth] --> TEN[tenants]
    TEN --> CON[contacts]
    TEN --> TPL[templates]
    CON --> CAMP[campaigns]
    TPL --> CAMP
    CAMP --> MSG[messaging]
    MSG --> PROV[providers]
    MSG --> WAL[wallet]
    PAYM[payments] --> WAL
    MSG --> REP[reports]
    MSG --> HOOK[webhooks]
    APIK[api_keys] --> MSG
    ADM[admin] -.-> TEN & WAL & PROV & PAYM
    AUD[audit] -.-> ALL((all modules))
```

| Module | Spec ref | Responsibilities |
| --- | --- | --- |
| `auth` | M1 | Registration, email verification, login, refresh, logout, password reset, sessions, (future) 2FA |
| `tenants` | M2 | Workspaces, profiles, invitations, memberships, roles, suspension |
| `contacts` | M3 | Contacts CRUD, groups, CSV/Excel import/export, dedupe, consent, suppression list |
| `templates` | M6 | Template CRUD, variable extraction, rendering |
| `campaigns` | M4, M5 | Drafts, scheduling, pause/cancel, duplication, progress |
| `messaging` | M4 | Message creation, segment calculation, cost estimation, dispatch, status lifecycle |
| `providers` | M7, M8 | Provider interface, demo gateway, real adapters, routing, DLR ingestion |
| `reports` | M9 | Aggregates, delivery rate, campaign comparison, exports |
| `wallet` | M10 | Ledger, reservations, captures, refunds, low-balance alerts, invoices |
| `payments` | M11 | Credit packages, checkout, PayHere notify verification, receipts |
| `api_keys` | M12 | Key generation/hashing/revocation, scopes, usage counters |
| `webhooks` | M12 | Endpoint config, signed event delivery, retries, delivery logs |
| `sender_ids` | M4, M13 | Sender ID requests and approval workflow |
| `admin` | M13 | Tenant management, pricing, providers, revenue, abuse monitoring, support tickets |
| `audit` | M14 | Immutable audit log of security- and money-relevant actions |

### 5.1 Layering inside a module

```
router.py      → HTTP only: parse request, call service, map errors to HTTP
schemas.py     → Pydantic request/response models
service.py     → Business rules, transactions, permission checks
repository.py  → SQLAlchemy queries (always tenant-scoped)
models.py      → ORM models
tasks.py       → Celery tasks owned by this module
events.py      → Domain events published by this module
```

---

## 6. Multi-Tenancy Design

### 6.1 Model: shared database, shared schema, `tenant_id` column

All tenants share one PostgreSQL database and schema. Every tenant-owned row carries `tenant_id`. This is the most cost-effective model for a large number of small/medium businesses and keeps migrations simple.

### 6.2 Defence in depth

| Layer | Mechanism |
| --- | --- |
| 1. Request | JWT/API key resolves `user_id`, `tenant_id`, `role`. Tenant ID is **never** taken from the request body. |
| 2. Application | Repository base class automatically adds `WHERE tenant_id = :current_tenant`. |
| 3. Database | **Row-Level Security**: each request/job runs `SET LOCAL app.tenant_id = '<uuid>'` inside its transaction; policies enforce it. |
| 4. Role | The application connects as a non-superuser role without `BYPASSRLS`. Admin/system jobs use a separate role. |
| 5. Tests | Automated cross-tenant tests attempt to read/write another tenant's data and must fail. |

### 6.3 RLS policy example

```sql
ALTER TABLE contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE contacts FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON contacts
    USING      (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
```

```python
# Set per transaction (works safely with connection pooling because of SET LOCAL)
async with session.begin():
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
    )
    ...
```

Celery tasks receive `tenant_id` as an argument and set the same context before touching the database.

### 6.4 Roles and permissions (RBAC)

| Permission | Owner | Admin | Manager | Operator | Viewer |
| --- | :-: | :-: | :-: | :-: | :-: |
| Manage billing / buy credits | ✅ | ✅ | ❌ | ❌ | ❌ |
| Manage users & roles | ✅ | ✅ | ❌ | ❌ | ❌ |
| Delete workspace / transfer ownership | ✅ | ❌ | ❌ | ❌ | ❌ |
| Manage API keys & webhooks | ✅ | ✅ | ❌ | ❌ | ❌ |
| Request sender IDs | ✅ | ✅ | ✅ | ❌ | ❌ |
| Manage contacts & groups | ✅ | ✅ | ✅ | ❌ | ❌ |
| Create/schedule campaigns, templates | ✅ | ✅ | ✅ | ❌ | ❌ |
| Send messages / launch approved campaigns | ✅ | ✅ | ✅ | ✅ | ❌ |
| View reports | ✅ | ✅ | ✅ | ✅ | ✅ |

Permissions are defined as constants (e.g. `campaigns:write`) and mapped to roles in code, enforced with a FastAPI dependency: `Depends(require("campaigns:write"))`.

---

## 7. Data Model

### 7.1 Entity-relationship overview

```mermaid
erDiagram
    TENANTS ||--o{ MEMBERSHIPS : has
    USERS ||--o{ MEMBERSHIPS : has
    TENANTS ||--o{ INVITATIONS : sends
    TENANTS ||--o{ CONTACTS : owns
    TENANTS ||--o{ CONTACT_GROUPS : owns
    CONTACTS }o--o{ CONTACT_GROUPS : "group_members"
    TENANTS ||--o{ SUPPRESSIONS : owns
    TENANTS ||--o{ TEMPLATES : owns
    TENANTS ||--o{ SENDER_IDS : requests
    TENANTS ||--o{ CAMPAIGNS : runs
    CAMPAIGNS ||--o{ MESSAGES : produces
    MESSAGES ||--o{ MESSAGE_EVENTS : "status history"
    PROVIDERS ||--o{ MESSAGES : routes
    TENANTS ||--|| WALLETS : has
    WALLETS ||--o{ LEDGER_ENTRIES : records
    TENANTS ||--o{ PAYMENTS : makes
    CREDIT_PACKAGES ||--o{ PAYMENTS : purchased
    TENANTS ||--o{ API_KEYS : issues
    TENANTS ||--o{ WEBHOOK_ENDPOINTS : configures
    WEBHOOK_ENDPOINTS ||--o{ WEBHOOK_DELIVERIES : logs
    TENANTS ||--o{ AUDIT_LOGS : generates
```

### 7.2 Core tables

All primary keys are UUIDs (v7 recommended for index locality). All tenant tables include `tenant_id`, `created_at`, `updated_at`.

**Identity & tenancy**

| Table | Key columns |
| --- | --- |
| `users` | id, email (unique, citext), password_hash, full_name, email_verified_at, locale, is_platform_admin, last_login_at |
| `tenants` | id, name, slug, business_type, status (`active`/`suspended`/`pending`), mode (`demo`/`live`), country, timezone (`Asia/Colombo`) |
| `memberships` | tenant_id, user_id, role, status |
| `invitations` | tenant_id, email, role, token_hash, expires_at, accepted_at |
| `refresh_tokens` | user_id, token_hash, family_id, expires_at, revoked_at, user_agent, ip |

**Contacts**

| Table | Key columns |
| --- | --- |
| `contacts` | tenant_id, phone_e164, first_name, last_name, email, attributes (JSONB), language, consent_status, consent_source, consent_at — **unique (tenant_id, phone_e164)** |
| `contact_groups` | tenant_id, name, description |
| `contact_group_members` | tenant_id, group_id, contact_id |
| `suppressions` | tenant_id, phone_e164, reason (`unsubscribed`/`complaint`/`invalid`/`manual`), created_at |
| `import_jobs` | tenant_id, file_key, status, total_rows, imported, duplicates, invalid, error_report_key |

**Messaging**

| Table | Key columns |
| --- | --- |
| `templates` | tenant_id, name, body, variables (text[]), category (`otp`/`transactional`/`promotional`), language |
| `sender_ids` | tenant_id, value (≤ 11 chars), status (`pending`/`approved`/`rejected`), provider_ref, reviewed_by |
| `campaigns` | tenant_id, name, body, sender_id_id, audience (JSONB: group ids / contact ids / uploaded list), status, scheduled_at, recurrence (RRULE), is_demo, estimated_segments, estimated_cost, reservation_id, stats (JSONB cached counters) |
| `messages` | tenant_id, campaign_id (nullable for API/OTP), source (`campaign`/`api`/`otp`), to_e164, sender, body, encoding (`GSM7`/`UCS2`), segments, unit_price, cost, status, provider_id, provider_message_id, is_demo, idempotency_key, error_code, submitted_at, delivered_at |
| `message_events` | tenant_id, message_id, status, raw_payload (JSONB), occurred_at |
| `providers` | name, type (`demo`/`smslenz`/`textlk`/`twilio`…), config_encrypted, priority, is_active, cost_per_segment |
| `otp_requests` | tenant_id, to_e164, code_hash, purpose, attempts, expires_at, verified_at |

**Billing**

| Table | Key columns |
| --- | --- |
| `wallets` | tenant_id (unique), balance (numeric, cached), reserved (numeric, cached), currency (`LKR`), low_balance_threshold |
| `ledger_entries` | tenant_id, wallet_id, type (`topup`/`reserve`/`release`/`charge`/`refund`/`adjustment`/`bonus`), amount (signed numeric(14,4)), balance_after, reference_type, reference_id, idempotency_key (unique), created_by — **append-only** |
| `credit_packages` | name, price_lkr, credits, bonus_credits, is_active |
| `pricing_rules` | scope (global/tenant), message_category, price_per_segment, effective_from |
| `payments` | tenant_id, package_id, order_id (unique), amount, currency, status, gateway, gateway_payment_id, raw_notification (JSONB), verified_at |
| `invoices` | tenant_id, payment_id, number (sequential), pdf_key, issued_at |

**Developer & platform**

| Table | Key columns |
| --- | --- |
| `api_keys` | tenant_id, name, prefix (e.g. `sf_live_ab12`), key_hash, scopes, last_used_at, revoked_at, expires_at |
| `api_request_logs` | tenant_id, api_key_id, method, path, status_code, latency_ms, created_at (partitioned / time-limited retention) |
| `webhook_endpoints` | tenant_id, url, secret_encrypted, events (text[]), is_active |
| `webhook_deliveries` | tenant_id, endpoint_id, event_type, payload, attempt, response_status, next_retry_at, status |
| `audit_logs` | tenant_id (nullable), actor_user_id, actor_type, action, target_type, target_id, metadata (JSONB), ip, created_at — **append-only** |
| `support_tickets` | tenant_id, subject, status, priority, assigned_to |

### 7.3 High-volume table strategy

- `messages`, `message_events`, `api_request_logs` are range-partitioned by month (`created_at`) once volume justifies it.
- Indexes: `messages (tenant_id, campaign_id, status)`, `messages (provider_id, provider_message_id)` for DLR lookup, `messages (tenant_id, created_at DESC)` for history.
- Campaign counters are maintained incrementally in `campaigns.stats` to avoid `COUNT(*)` on large tables; a periodic job reconciles them.

---

## 8. Messaging Engine

### 8.1 Message status lifecycle

```mermaid
stateDiagram-v2
    [*] --> queued: created & funds reserved
    queued --> rejected: validation/suppression failure
    queued --> submitting: worker picked up
    submitting --> accepted: provider accepted (has provider_message_id)
    submitting --> queued: transient error (retry with backoff)
    submitting --> failed: permanent error / retries exhausted
    accepted --> delivered: DLR delivered
    accepted --> undelivered: DLR failed / expired
    accepted --> unknown: no DLR within window
    delivered --> [*]
    undelivered --> [*]
    failed --> [*]
    rejected --> [*]
    unknown --> [*]
```

> **Accepted ≠ Delivered.** Reports show *accepted* (provider took the message) separately from *delivered* (confirmed by delivery report). Delivery rate = `delivered / total submitted × 100`.

### 8.2 Campaign lifecycle

```mermaid
stateDiagram-v2
    [*] --> draft
    draft --> scheduled: schedule (funds reserved)
    draft --> processing: send now (funds reserved)
    scheduled --> draft: unschedule (funds released)
    scheduled --> cancelled: cancel (funds released)
    scheduled --> processing: scheduled_at reached
    processing --> paused: pause
    paused --> processing: resume
    paused --> cancelled: cancel (unsent funds released)
    processing --> completed: all messages terminal
    completed --> [*]
    cancelled --> [*]
```

### 8.3 Campaign send flow

```mermaid
sequenceDiagram
    autonumber
    actor U as Business User
    participant API as FastAPI
    participant DB as PostgreSQL
    participant Q as Redis (Celery)
    participant EXP as Worker: campaigns.expand
    participant SND as Worker: sms.send
    participant P as Provider Adapter
    participant SP as SMS Provider

    U->>API: POST /campaigns/{id}/send
    API->>DB: Validate sender ID approved, tenant active, audience size
    API->>API: Estimate segments × price
    API->>DB: BEGIN; lock wallet; check available ≥ estimate;<br/>insert ledger 'reserve'; campaign → processing; COMMIT
    API->>Q: enqueue expand_campaign(campaign_id)
    API-->>U: 202 Accepted

    Q->>EXP: expand_campaign
    loop batches of 1,000 contacts
        EXP->>DB: Load contacts, skip suppressed / no consent / invalid
        EXP->>EXP: Render personalised body, compute encoding & segments
        EXP->>DB: Bulk insert messages (status=queued)
        EXP->>Q: enqueue send_message(id) (or provider batch)
    end

    Q->>SND: send_message(id)
    SND->>DB: Lock row, ensure status=queued (idempotent)
    SND->>P: send(to, sender, body)
    P->>SP: HTTPS (HTTPX, timeout)
    SP-->>P: provider_message_id
    P-->>SND: SendResult
    SND->>DB: status=accepted; ledger 'charge' (from reservation)

    SP-)API: POST /callbacks/dlr/{provider}
    API->>DB: Verify, map status, update message, insert message_event
    API->>Q: enqueue webhook delivery + refund if billable failure
```

### 8.4 Validation pipeline (before a message is queued)

1. Tenant is `active` (not suspended) and in the right mode (demo/live).
2. Sender ID is approved for the tenant (live mode).
3. Number normalises to valid E.164; Sri Lankan mobile pattern `+947[0-9]{8}` for local routes.
4. Number is **not** in the tenant's suppression list (and global block list).
5. For promotional messages: contact has consent and the message includes an opt-out instruction.
6. Duplicate numbers within one campaign are removed.
7. Template variables resolve (missing variables → configurable: skip contact or use fallback).
8. Wallet available balance (`balance − reserved`) covers the estimated cost.
9. Optional quiet hours for promotional messages (e.g. no sends 21:00–08:00 Asia/Colombo).

### 8.5 Scheduling

- **Celery Beat** runs `dispatch_due_campaigns` every minute: selects `scheduled` campaigns with `scheduled_at <= now()` using `SELECT … FOR UPDATE SKIP LOCKED`, moves them to `processing`, and enqueues expansion. This is safe even if two Beat instances accidentally run.
- Recurring campaigns store an iCal **RRULE** (e.g. every Monday 10:00 Asia/Colombo). On each run, the next occurrence is materialised as a new child campaign.
- All times stored in UTC; displayed in the tenant's timezone.

### 8.6 Queues and workers

| Queue | Tasks | Notes |
| --- | --- | --- |
| `campaigns` | `expand_campaign`, `finalize_campaign` | CPU/DB heavy, low concurrency |
| `sms.send` | `send_message`, `send_batch` | I/O bound; concurrency limited by provider TPS |
| `sms.priority` | OTP and transactional API sends | Dedicated workers so bulk campaigns never delay OTPs |
| `dlr` | `process_dlr`, `poll_pending_dlrs` | |
| `webhooks` | `deliver_webhook` | Exponential backoff, up to ~24 h |
| `default` | imports, exports, emails, invoices, reconciliation | |

Task settings: `acks_late=True`, `task_reject_on_worker_lost=True`, idempotent task bodies, exponential backoff with jitter, dead-letter after max retries (marked `failed` + alert).

### 8.7 OTP service

- `POST /api/v1/otp/send` generates a numeric code (CSPRNG), stores **only its hash** with expiry (e.g. 5 minutes) and max attempts (e.g. 5).
- `POST /api/v1/otp/verify` compares in constant time, increments attempts, marks verified once.
- Rate limits per destination number and per tenant to prevent SMS pumping fraud.
- Routed through `sms.priority`.

---

## 9. SMS Provider Adapter Layer

### 9.1 Interface

```python
class SmsProvider(Protocol):
    code: str                         # "demo", "smslenz", "textlk", "twilio"

    async def send(self, msg: OutboundSms) -> SendResult: ...
    async def send_batch(self, msgs: list[OutboundSms]) -> list[SendResult]: ...
    async def get_status(self, provider_message_id: str) -> DeliveryStatus: ...
    async def get_balance(self) -> ProviderBalance: ...
    def parse_dlr(self, request: DlrRequest) -> list[DeliveryReport]: ...
    def verify_callback(self, request: DlrRequest) -> bool: ...
```

`SendResult` normalises every provider into: `accepted | retryable_error | permanent_error`, `provider_message_id`, `error_code`, `raw`.

### 9.2 Routing

```mermaid
flowchart LR
    MSG[Message] --> MODE{Tenant / message<br/>is demo?}
    MODE -- yes --> DEMO[DemoProvider]
    MODE -- no --> ROUTER[ProviderRouter]
    ROUTER --> RULES[Rules: priority, tenant override,<br/>message category, health]
    RULES --> P1[Primary provider]
    RULES -. failover on outage .-> P2[Secondary provider]
```

- Provider credentials are stored encrypted (`config_encrypted`, AES-GCM with a key from environment/secret manager).
- A **circuit breaker** per provider marks it unhealthy after repeated timeouts and fails over (transactional/OTP only; campaigns pause instead to avoid duplicate sends).
- Per-provider **token-bucket rate limiter** in Redis enforces the provider's allowed TPS.

### 9.3 Demo SMS Gateway (Module 7)

A fully in-process provider used in development, tests and for tenants in demo mode.

| Behaviour | Implementation |
| --- | --- |
| Acceptance | Returns `accepted` with `provider_message_id = "demo-<uuid>"` |
| Outcome distribution | Configurable, default ≈ 90 % delivered, 6 % failed, 4 % pending/unknown |
| Latency | DLR scheduled via Celery `countdown` (random 2–30 s) to mimic real callbacks |
| Failure injection | Magic test numbers: e.g. `+94770000001` always fails, `+94770000002` times out, `+94770000003` stays pending |
| Retry testing | Configurable transient error rate to exercise retries |
| Determinism | Optional seed for reproducible test runs |
| Labelling | `is_demo = true` on messages/campaigns; UI shows a **DEMO** badge; demo usage uses a separate demo credit balance and is never billed |

Because the demo provider implements the same interface and emits DLRs through the same `process_dlr` path, switching to a real provider requires no change to the messaging engine.

### 9.4 Real providers (Module 8)

Candidate providers: SMSlenz, Text.lk (local), Twilio, Sinch (international). Selection criteria: reseller terms, sender ID registration process, Sri Lankan network coverage, DLR support, TPS, pricing, API reliability.

Each adapter handles: authentication, request mapping, error-code mapping to `retryable`/`permanent`, DLR parsing/verification, balance checks (alert super-admin when low), and daily cost reconciliation against provider reports.

---

## 10. Wallet, Billing and Payments

### 10.1 Ledger model

The wallet balance is the sum of immutable ledger entries. `wallets.balance` and `wallets.reserved` are cached values updated in the **same transaction** as each ledger insert (with `SELECT … FOR UPDATE` on the wallet row) and verified by a nightly reconciliation job.

| Entry type | Effect | When |
| --- | --- | --- |
| `topup` | +balance | Verified payment |
| `bonus` / `adjustment` | ±balance | Admin action (audited) |
| `reserve` | +reserved | Campaign scheduled/sent, API send accepted |
| `release` | −reserved | Campaign cancelled, unsent messages, estimate > actual |
| `charge` | −balance, −reserved | Message submitted to provider |
| `refund` | +balance | Eligible failure (e.g. provider rejected before carrier) per billing policy |

`available = balance − reserved`. Sending is blocked if `available < estimated_cost`.

### 10.2 Pricing

- Price is **per segment**, not per message (see §15).
- `pricing_rules` allow global defaults, per-category pricing (OTP/transactional/promotional) and tenant-specific overrides (enterprise contracts).
- Amounts stored as `numeric(14,4)` in LKR — never floats.

### 10.3 Payment flow (PayHere)

```mermaid
sequenceDiagram
    autonumber
    actor U as Business Owner
    participant WEB as Next.js
    participant API as FastAPI
    participant DB as PostgreSQL
    participant PH as PayHere

    U->>WEB: Choose credit package
    WEB->>API: POST /billing/checkout {package_id}
    API->>DB: Insert payment (status=pending, order_id)
    API-->>WEB: Checkout params + server-generated hash
    WEB->>PH: Redirect / JS SDK checkout
    PH-->>U: Payment page
    PH->>API: POST /callbacks/payhere/notify (server-to-server)
    API->>API: Verify md5sig with merchant secret,<br/>check merchant_id, amount, currency match order
    API->>DB: BEGIN; lock payment row;<br/>if already 'completed' → no-op (idempotent);<br/>status=completed; ledger 'topup' (idempotency_key = payment id); COMMIT
    API-->>PH: 200 OK
    PH-->>WEB: Redirect to return_url
    WEB->>API: GET /billing/payments/{order_id}
    API-->>WEB: Status (wallet updated only via notify)
```

Rules:

- **Only the verified server-to-server notification credits the wallet.** The browser return URL is display-only.
- Notification signature is checked, and the amount/currency/order must match the stored pending payment.
- Unique `ledger_entries.idempotency_key` makes double crediting impossible even under duplicate notifications.
- Receipts/invoices are generated asynchronously (PDF to object storage, emailed to owner).

### 10.4 Subscriptions (later phase)

Monthly plans are modelled as `subscriptions` (plan, period, status, included credits). A Beat job renews plans and posts included credits as `bonus` ledger entries. Kept out of the MVP; credit packages come first.

---

## 11. Developer API and Webhooks

### 11.1 API surface (v1)

Base URL: `https://api.smsflow.lk/api/v1`

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/sms/send` | Send a single SMS |
| `POST` | `/sms/bulk` | Send up to N messages in one call |
| `GET` | `/sms/{message_id}` | Message status |
| `GET` | `/sms` | List/filter messages |
| `POST` | `/otp/send` | Send OTP |
| `POST` | `/otp/verify` | Verify OTP |
| `GET` | `/balance` | Wallet balance |
| `GET/POST/…` | `/contacts`, `/groups`, `/templates`, `/campaigns` | Same resources as dashboard |

The dashboard uses the same versioned API (authenticated with JWT); external apps use API keys. One API, two auth methods.

### 11.2 Example

```http
POST /api/v1/sms/send
Authorization: Bearer sf_live_ab12cd34_xxxxxxxxxxxxxxxxxxxxxxxx
Idempotency-Key: order-10045-confirmation
Content-Type: application/json

{
  "to": "+94771234567",
  "message": "Your order has been confirmed.",
  "sender_id": "ABCSTORE"
}
```

```json
HTTP/1.1 202 Accepted
{
  "message_id": "msg_01J9Z3K8V2…",
  "status": "queued",
  "segments": 1,
  "encoding": "GSM7",
  "cost": 0.85,
  "currency": "LKR",
  "is_demo": false
}
```

### 11.3 API keys

- Format: `sf_{live|test}_{prefix}_{secret}`. Only `prefix` and a **SHA-256 hash** of the full key are stored; the key is shown once at creation.
- `test` keys always route to the demo provider.
- Scopes: `sms:send`, `sms:read`, `otp`, `contacts:read`, `contacts:write`, `balance:read`.
- Revocation is immediate; rotation = create new key, migrate, revoke old.
- Authentication results cached in Redis briefly to reduce DB lookups.

### 11.4 Rate limiting

- Redis sliding-window/token-bucket per API key and per tenant (e.g. 10 req/s default, configurable per plan).
- Responses include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `Retry-After` on `429`.
- Separate per-destination-number limits for OTP.

### 11.5 Idempotency

`Idempotency-Key` header on send endpoints: the `(tenant_id, key)` pair and response are stored for 24 h. Repeating the request returns the original response without sending again.

### 11.6 Webhooks

Events: `message.accepted`, `message.delivered`, `message.failed`, `campaign.completed`, `wallet.low_balance`, `payment.completed`.

```http
POST https://customer.example.com/hooks/smsflow
SMSFlow-Event: message.delivered
SMSFlow-Delivery: whd_01J9…
SMSFlow-Timestamp: 1767225600
SMSFlow-Signature: v1=<hex HMAC-SHA256(secret, timestamp + "." + body)>
```

- Delivered by `webhooks` workers with exponential backoff (e.g. 1 m, 5 m, 30 m, 2 h, 6 h, 12 h), then marked failed.
- Endpoint auto-disabled after sustained failures; owner notified.
- Delivery log and manual "resend" in the developer portal.
- SSRF protection: webhook URLs must be HTTPS, resolve to public IPs, and are re-checked at delivery time.

### 11.7 Documentation

FastAPI generates the OpenAPI spec; the public developer portal renders it (Redoc/Scalar) with code samples (cURL, PHP, Node.js, Python) and a sandbox using `test` keys.

---

## 12. Authentication and Authorization

### 12.1 Dashboard authentication

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant WEB as Next.js
    participant API as FastAPI
    participant DB as PostgreSQL

    U->>WEB: Email + password
    WEB->>API: POST /auth/login
    API->>DB: Load user, verify Argon2 hash, check verified/active
    API-->>WEB: access token (JWT, 15 min) in body/memory<br/>refresh token (opaque, 30 days) in HttpOnly Secure SameSite cookie
    WEB->>API: API calls with Authorization: Bearer <access>
    Note over WEB,API: On 401 → POST /auth/refresh (cookie)
    API->>DB: Validate refresh hash, rotate (revoke old, issue new, same family)
    API-->>WEB: New access + refresh
    Note over API,DB: Reuse of a revoked refresh token → revoke entire family (theft detection)
```

- JWT claims: `sub` (user id), `tid` (active tenant), `role`, `exp`, `jti`. Signed with RS256/EdDSA (asymmetric keys allow future services to verify without the signing secret).
- Users belonging to multiple tenants switch workspace via `POST /auth/switch-tenant` (new access token).
- Email verification and password-reset tokens are random, single-use, hashed in DB, short expiry.
- Login rate limiting and progressive lockout per account and IP.
- **Future:** TOTP 2FA (required for owners and platform admins).

### 12.2 Authorization

- `get_current_principal()` dependency → `Principal(user_id | api_key_id, tenant_id, role, scopes)`.
- `require(permission)` dependency checks RBAC (users) or scopes (API keys).
- Super-admin endpoints under `/admin/*` require `is_platform_admin` + 2FA, and run with a dedicated DB role; every action is audit-logged.

---

## 13. Security Architecture

| Area | Control |
| --- | --- |
| Transport | HTTPS everywhere (TLS 1.2+), HSTS, Nginx with modern ciphers |
| Passwords | Argon2id; minimum length + breached-password check (optional) |
| Tokens | Short-lived JWT access, rotating refresh tokens, HttpOnly/Secure/SameSite cookies |
| Tenant isolation | App-level scoping + PostgreSQL RLS + automated isolation tests |
| Secrets | Env vars / secret manager; provider credentials and webhook secrets encrypted at rest (AES-GCM) |
| API keys | Hashed, prefixed, scoped, revocable, last-used tracking |
| Input | Pydantic validation, file size/type limits on imports, CSV formula-injection escaping on exports |
| Web | CSP, X-Frame-Options, CSRF protection for cookie-authenticated endpoints, CORS allow-list |
| Callbacks | Signature verification (PayHere md5sig, provider DLR auth/IP allow-list) |
| Outbound | SSRF guard on webhook URLs; HTTPX timeouts |
| Abuse | Rate limits, new-tenant sending caps, content keyword screening, sudden-volume anomaly alerts, OTP pumping detection, sender ID approval workflow |
| Messaging compliance | Consent tracking, mandatory opt-out (`STOP`) handling, suppression lists, quiet hours |
| Audit | Append-only `audit_logs` for logins, role changes, key creation, payments, admin actions |
| Data | Encrypted backups (daily full + WAL/PITR), tested restores, data retention policy, tenant data export/deletion on request |
| Compliance | Designed with Sri Lanka's Personal Data Protection Act (PDPA, No. 9 of 2022) and TRCSL requirements in mind |
| Dependencies | Dependabot, `pip-audit`, `npm audit`, container image scanning in CI |

---

## 14. Frontend Architecture

### 14.1 Applications (single Next.js project, route groups)

```
app/
├── (marketing)/          # Public: /, /features, /pricing, /contact
├── (docs)/               # Developer documentation
├── (auth)/               # /login, /register, /verify-email, /reset-password
├── (dashboard)/          # Authenticated tenant area
│   ├── overview/
│   ├── contacts/         # list, import, groups, suppressions
│   ├── campaigns/        # list, create wizard, detail/progress
│   ├── messages/         # quick send, history
│   ├── templates/
│   ├── reports/
│   ├── billing/          # wallet, packages, transactions, invoices
│   ├── developers/       # API keys, webhooks, logs
│   └── settings/         # profile, team, sender IDs, workspace
└── (admin)/              # Super-admin console (separate layout + guard)
```

### 14.2 Key patterns

- **Server Components** for marketing/docs pages (SEO, speed); **Client Components** with TanStack Query for interactive dashboard pages.
- Typed API client generated from the backend OpenAPI schema (`openapi-typescript`) so frontend and backend types never drift.
- Middleware protects `(dashboard)` and `(admin)` route groups.
- Campaign wizard: Audience → Message (live segment/character counter, variable picker, preview) → Sender & schedule → Cost estimate & confirm.
- Live campaign progress via polling (MVP) → Server-Sent Events later.
- Persistent **DEMO MODE** banner and badges when the tenant or campaign is in demo mode.
- Accessibility: keyboard navigation, ARIA labels, colour-contrast compliant charts.

---

## 15. Localization and SMS Encoding

### 15.1 Encoding and segmentation

| Encoding | Used when | Single SMS | Per segment when concatenated |
| --- | --- | --- | --- |
| GSM-7 | Only GSM 03.38 characters (basic Latin) | 160 chars | 153 chars |
| UCS-2 | Any non-GSM character (Sinhala, Tamil, emoji, some symbols) | 70 chars | 67 chars |

- GSM-7 extension characters (`{ } [ ] ~ \ | ^ €`) count as 2 characters.
- One Sinhala/Tamil character switches the whole message to UCS-2 — the UI warns when this happens (e.g. a stray emoji in an English message).
- Segments are computed **after** personalisation for each recipient, so cost estimates use the longest-variable assumption and actual cost is computed per message.
- A shared `sms_segments` utility (Python) is mirrored in TypeScript for the live counter; both are tested against the same fixture set.

### 15.2 UI localisation

- UI strings in English, Sinhala and Tamil via `next-intl`; user locale stored on profile.
- Fonts with full Sinhala/Tamil coverage (e.g. Noto Sans Sinhala, Noto Sans Tamil).
- Dates/currency formatted for `Asia/Colombo` and LKR.

---

## 16. Observability

| Signal | Tooling | Examples |
| --- | --- | --- |
| Errors | Sentry (backend, workers, frontend) | Exceptions with tenant/request context (no PII in payloads) |
| Logs | Structured JSON logs (structlog) → stdout → log aggregator | `request_id`, `tenant_id`, `message_id`, `campaign_id` |
| Metrics | Prometheus + Grafana (optional at MVP) | Queue depth, send TPS, provider latency/error rate, DLR lag, delivery rate, API p95 |
| Queues | Flower | Worker health, task failures |
| Uptime | External uptime monitor | `/health/live`, `/health/ready` (DB + Redis checks) |
| Business alerts | Email/Slack to admins | Provider balance low, payment failures spike, abnormal tenant volume, reconciliation mismatch |

A `request_id` is generated at Nginx/API and propagated into Celery task headers so a single send can be traced end to end.

---

## 17. Deployment Architecture

### 17.1 Environments

| Environment | Purpose | SMS provider |
| --- | --- | --- |
| `local` | Docker Compose on developer machine | Demo only |
| `staging` | Pre-production, mirrors prod | Demo + provider sandbox |
| `production` | Live customers | Real providers (+ demo for demo tenants / test keys) |

### 17.2 Production topology (initial)

```mermaid
flowchart TB
    INTERNET((Internet)) --> CF[DNS / CDN / WAF<br/>e.g. Cloudflare]
    CF --> LB[Nginx / Load Balancer<br/>TLS]

    subgraph VM_or_Cluster [Application hosts - Docker]
        WEB1[web x2]
        API1[api x2]
        WS[worker-send xN]
        WD[worker-default x2]
        BT[beat x1]
    end

    LB --> WEB1
    LB --> API1

    subgraph Managed_Data [Managed services]
        PG[(PostgreSQL<br/>automated backups + PITR)]
        RD[(Redis)]
        S3[(Object storage)]
    end

    API1 --> PG & RD & S3
    WS --> PG & RD
    WD --> PG & RD & S3
    BT --> RD
```

- **Start:** a single cloud VM (or two) running Docker Compose + managed PostgreSQL/Redis. Simple and affordable.
- **Grow:** move to a container platform (Kubernetes, ECS, or similar) when multiple hosts and autoscaling are needed. Container images are identical either way.
- Prefer hosting in a region with low latency to Sri Lanka (e.g. Mumbai/Singapore) while checking data-residency obligations.

### 17.3 CI/CD (GitHub Actions)

```mermaid
flowchart LR
    PR[Pull request] --> LINT[Lint & type-check<br/>ruff, mypy, eslint, tsc]
    LINT --> TEST[Tests<br/>pytest + Postgres/Redis services,<br/>vitest, Playwright]
    TEST --> SEC[Security scans<br/>pip-audit, npm audit, image scan]
    SEC --> BUILD[Build Docker images]
    BUILD --> MAIN{Merged to main?}
    MAIN -- yes --> STG[Deploy to staging<br/>+ alembic upgrade]
    STG --> SMOKE[Smoke tests]
    SMOKE --> APPROVE{Manual approval}
    APPROVE --> PROD[Deploy to production]
```

- Migrations run as a one-off job before new app containers start; migrations must be backward compatible (expand → migrate → contract).
- Images tagged with git SHA; rollback = redeploy previous tag.

---

## 18. Scalability and Reliability

| Concern | Approach |
| --- | --- |
| API load | Stateless API replicas behind LB; Redis caching for hot reads (balances, API key auth) |
| Large campaigns (100k+) | Batched expansion (1,000/batch), bulk inserts, provider batch endpoints, per-provider throttling |
| Fairness between tenants | Per-tenant concurrency caps so one large campaign cannot starve others; separate priority queue for OTP/transactional |
| Duplicate sends | Row lock + status check before send; idempotency keys; `acks_late` with idempotent tasks |
| Provider outage | Retries with backoff, circuit breaker, failover for transactional traffic, campaign auto-pause |
| Worker crash | `acks_late` + `reject_on_worker_lost` → task redelivered; idempotency prevents double send |
| Lost DLRs | `poll_pending_dlrs` queries provider status for messages accepted > N minutes; final `unknown` after window |
| DB growth | Partitioning of message/event/log tables; archival of old partitions; read replica for reports |
| Data loss | Managed Postgres with PITR, daily backups, quarterly restore drills |
| Redis loss | Redis is not the source of truth — queued-but-unsent messages are recoverable from `messages.status = queued` by a sweeper job |

**Initial capacity target:** 50 tenants, 100k messages/day, OTP end-to-end p95 < 5 s (excluding carrier delay), API p95 < 300 ms.

---

## 19. Repository Structure

Monorepo:

```
smsflow/
├── ARCHITECTURE.md
├── README.md
├── docker-compose.yml               # postgres, redis, api, workers, beat, web, nginx, flower
├── docker-compose.prod.yml
├── .github/workflows/               # ci.yml, deploy.yml
├── infra/
│   ├── nginx/
│   └── scripts/                     # backup, restore, seed
├── backend/
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── alembic/                     # migrations (incl. RLS policies)
│   ├── app/
│   │   ├── main.py                  # FastAPI app factory, routers
│   │   ├── core/                    # config, security, db session, tenancy context,
│   │   │                            # logging, errors, rate limiting, idempotency
│   │   ├── workers/                 # celery_app.py, beat schedule, queue routing
│   │   ├── shared/                  # phone utils, sms_segments, money, pagination
│   │   └── modules/
│   │       ├── auth/
│   │       ├── tenants/
│   │       ├── contacts/
│   │       ├── templates/
│   │       ├── campaigns/
│   │       ├── messaging/
│   │       ├── providers/
│   │       │   ├── base.py          # SmsProvider protocol, result types
│   │       │   ├── router.py        # provider selection, circuit breaker
│   │       │   ├── demo.py          # Demo SMS Gateway
│   │       │   ├── smslenz.py
│   │       │   ├── textlk.py
│   │       │   └── twilio.py
│   │       ├── otp/
│   │       ├── reports/
│   │       ├── wallet/
│   │       ├── payments/
│   │       ├── api_keys/
│   │       ├── webhooks/
│   │       ├── sender_ids/
│   │       ├── admin/
│   │       └── audit/
│   └── tests/
│       ├── unit/
│       ├── integration/
│       ├── tenancy/                 # cross-tenant isolation tests
│       └── fixtures/
└── frontend/
    ├── package.json
    ├── Dockerfile
    ├── next.config.ts
    ├── messages/                    # en.json, si.json, ta.json
    └── src/
        ├── app/                     # route groups (see §14.1)
        ├── components/              # ui/, forms/, charts/, layout/
        ├── lib/                     # api client (generated), auth, sms-segments.ts
        ├── hooks/
        └── types/
```

---

## 20. Testing Strategy

| Level | Scope | Tools |
| --- | --- | --- |
| Unit | Segment calculator, phone validation, template rendering, pricing, ledger math, signature verification | pytest, vitest |
| API | Each endpoint: auth, permissions, validation, error codes | pytest + HTTPX `AsyncClient` |
| Integration | Real Postgres + Redis (Docker/testcontainers); Celery tasks end-to-end with the demo provider | pytest |
| Tenant isolation | For every tenant resource: tenant B cannot list/read/update/delete tenant A's data, at API and at DB (RLS) level | pytest (dedicated suite, required in CI) |
| Financial | Concurrent sends cannot overdraw; duplicate payment notifications credit once; reconciliation matches | pytest with concurrency |
| Contract | Provider adapters against recorded provider responses | pytest + respx |
| E2E | Register → import contacts → buy credits (sandbox) → send campaign → view report | Playwright |
| Load | 100k-recipient campaign, API burst, OTP throughput | Locust / k6 |
| Security | OWASP ZAP baseline scan, dependency audits, manual review of auth/billing | ZAP, pip-audit, npm audit |

---

## 21. Implementation Roadmap

Aligned with the project phases; the **MVP** is phases 1–6 with the demo gateway.

| Phase | Deliverables | Architectural milestone |
| --- | --- | --- |
| 1. Design | This document, ERD, API spec draft, UI wireframes | Decisions recorded (ADRs) |
| 2. Backend foundation | FastAPI skeleton, config, DB, Alembic, auth, tenants, RBAC, RLS, audit | Tenant isolation proven by tests |
| 3. Frontend foundation | Next.js shell, auth pages, dashboard layout, i18n, generated API client | End-to-end login |
| 4. Contacts & campaigns | Contacts, groups, import/export, suppression, templates, campaign wizard, scheduler | Celery + Beat running |
| 5. Demo gateway | Provider interface, demo provider, send pipeline, DLR processing, reports | Full send lifecycle working with no real SMS |
| 6. Wallet & payments | Ledger, reservations, pricing, PayHere sandbox, invoices | No-overdraw + idempotent top-up verified |
| 7. Developer API | API keys, `/sms/send`, OTP, idempotency, rate limits, webhooks, docs portal | Public API v1 |
| 8. Real provider | First production adapter, sender ID workflow, reconciliation, failover | Live SMS delivered |
| 9. Hardening | Security tests, load tests, abuse controls, backups/restore drill | Launch readiness checklist |
| 10. Launch | Production deployment, monitoring, support processes | Commercial launch |

---

## 22. Future Extensions

The data model separates **channel** from **message** so new channels plug into the same engine:

| Extension | Architectural hook |
| --- | --- |
| WhatsApp Business | New `channel` column on messages; `WhatsAppProvider` implementing a `ChannelProvider` interface; template approval sync |
| Email channel | Same pattern with an email provider adapter |
| AI message generation | `ai` module calling an LLM to draft English/Sinhala/Tamil copy; output always passes through segment counter and compliance checks before saving as a template |
| Marketing automation | Event ingestion endpoint (`POST /events`) + rule/journey engine that creates messages via the existing messaging service |
| Customer analytics | Read replica / analytics warehouse fed from message and event tables |
| Inbound SMS / two-way | Provider MO callbacks → `inbound_messages`; automatic `STOP` handling into suppressions |
| Mobile app | Uses the same public API with JWT auth |

---

## 23. Architecture Decision Records

| # | Decision | Rationale | Alternatives considered |
| --- | --- | --- | --- |
| ADR-001 | Modular monolith (FastAPI) + separate worker processes | Fast to build for a small team; clean module boundaries allow later extraction | Microservices from day one (too much operational overhead) |
| ADR-002 | Shared-schema multi-tenancy with `tenant_id` + PostgreSQL RLS | Cheapest at scale for many SMB tenants; RLS protects against missed filters | Schema-per-tenant, database-per-tenant (harder migrations, higher cost) |
| ADR-003 | Celery + Redis for async processing | Mature, Python-native, supports scheduling, retries, routing | RQ (simpler, fewer features), Kafka (overkill for MVP) |
| ADR-004 | Append-only ledger for wallet | Auditable, reconcilable, prevents silent balance corruption | Single mutable balance column |
| ADR-005 | Provider adapter interface with demo provider | Build and test the full product without SMS cost; swap providers without engine changes | Hard-coding one provider API |
| ADR-006 | Per-segment billing | Matches provider cost model, especially for UCS-2 Sinhala/Tamil | Per-message billing (loss-making for long/Unicode messages) |
| ADR-007 | Only server-to-server payment notifications credit wallets | Browser redirects can be forged or lost | Crediting on return URL |
| ADR-008 | Same versioned REST API for dashboard and external developers | One implementation, consistent behaviour, dogfooding | Separate internal and public APIs |
| ADR-009 | Next.js single app with route groups for marketing, dashboard and admin | Shared components and auth; simpler deployment | Separate SPA for admin (can be split later if needed) |

---

*This document should be updated whenever a significant architectural decision changes. New decisions are added to §23 as ADRs.*
