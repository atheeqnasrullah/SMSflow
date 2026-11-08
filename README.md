# SMSFlow

> **One Platform. Every Customer. Smarter Communication.**

A multi-tenant SaaS for bulk SMS, OTP, transactional notifications and scheduled campaigns for Sri Lankan businesses. The design is in [ARCHITECTURE.md](ARCHITECTURE.md).

| Part | Stack | Path |
| --- | --- | --- |
| API + workers | FastAPI, SQLAlchemy 2 (async), Alembic, Celery + Redis, PostgreSQL 16 with RLS | [backend/](backend/) |
| Web (marketing, dashboard, admin) | Next.js 15 App Router, TypeScript, Tailwind, TanStack Query, next-intl (en/si/ta) | [frontend/](frontend/) |
| Infra | Docker Compose, Nginx, GitHub Actions | [docker-compose.yml](docker-compose.yml), [infra/](infra/), [.github/workflows/](.github/workflows/) |

## Quick start: Docker (full stack)

```bash
cp .env.example .env
docker compose up --build -d
docker compose run --rm api python -m app.scripts.seed --demo-tenant
```

- App: http://localhost
- API reference: http://localhost/api/docs
- Flower (queue monitoring): http://localhost:5555

Seeded logins (local only; change them in `.env` for any shared environment):

| Who | Email | Password |
| --- | --- | --- |
| Platform admin | `admin@smsflow.lk` | `ChangeMe-Admin-123` |
| Demo business owner ("Lanka Mart") | `owner@lankamart.lk` | `DemoOwner-123` |

## Quick start: without Docker (SQLite + in-process tasks)

The backend runs without Postgres or Redis. Tasks and the Beat schedule run inside the API process (`TASK_MODE=inline`).

```bash
# API
cd backend
python -m venv .venv && .venv/Scripts/activate        # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
python -m app.scripts.seed --demo-tenant
uvicorn app.main:app --reload --port 8000

# Web (second terminal)
cd frontend
npm install
npm run dev                                            # http://localhost:3000 (proxies /api to :8000)
```

If port 8000 is taken, start the API on another port and set `API_ORIGIN=http://localhost:<port>` before `npm run dev` or `npm run build`.

## Tests

```bash
cd backend && pytest -q          # 60 tests: unit, API, campaigns, billing, webhooks, tenant isolation
cd frontend && npm test          # segment counter, using the same fixtures as the backend
```

Set `TEST_DATABASE_URL` (app role) and `TEST_ADMIN_DATABASE_URL` (owner role) to PostgreSQL URLs to also run the Row-Level Security tests. CI does this; see [ci.yml](.github/workflows/ci.yml).

## Demo gateway

New workspaces start in **demo mode** with 500 demo credits. Messages go through the built-in Demo SMS Gateway, which sends simulated delivery reports through the same pipeline real providers use. Nothing is billed. Magic numbers:

| Number | Behaviour |
| --- | --- |
| `+94770000001` | always fails |
| `+94770000002` | times out (exercises retries) |
| `+94770000003` | accepted, never gets a delivery report (→ `unknown` after 48 h) |

To go live, an admin switches the workspace to live mode in **Admin console → Tenants** and approves a sender ID. A real provider must be configured under **Providers** (`textlk`, `smslenz`, `twilio` or `generic`).

## Things to configure before production

- **Secrets:** `JWT_SECRET` (or RS256/EdDSA keys), `ENCRYPTION_KEY`, `OTP_HASH_SECRET`, database passwords.
- **PayHere:** set `PAYHERE_MERCHANT_ID` and `PAYHERE_MERCHANT_SECRET`, and set `PAYHERE_SANDBOX=false` for production. The notify URL is `/api/v1/callbacks/payhere/notify`. Only the verified server-to-server notification credits a wallet.
- **SMS providers:** the Text.lk and SMSlenz adapters ([generic_http.py](backend/app/modules/providers/generic_http.py)) use configurable field mappings. **Verify them against each provider's current API docs** and record contract-test fixtures before sending live traffic.
- **SMTP** for verification, invitation, reset and receipt emails. Without SMTP, emails are only logged.
- **Object storage:** [storage.py](backend/app/shared/storage.py) writes to the local filesystem (a Docker volume). Swap in S3-compatible storage for multi-host deployments.
- **TLS:** edit `server_name` and the certificate paths in [nginx.prod.conf](infra/nginx/nginx.prod.conf).
