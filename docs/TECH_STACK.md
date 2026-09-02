# Plumbit ERP technology stack

Authoritative stack for this backend. Instruction files and [ARCHITECTURE.md](ARCHITECTURE.md)
point here. Do not introduce a new dependency unless something on this list cannot solve the
problem.

## Runtime and API

| Layer | Choice |
| --- | --- |
| Language | Python 3.13 |
| API | FastAPI, Pydantic v2, Pydantic Settings |
| ASGI (local) | Uvicorn |
| ASGI (production) | Same FastAPI app on AWS Lambda behind API Gateway |
| Auth | JWT (PyJWT), bcrypt password hashing |

## Data

| Layer | Choice |
| --- | --- |
| Database | PostgreSQL (local) / Amazon RDS PostgreSQL (production) |
| ORM | SQLAlchemy 2.x async + asyncpg |
| Migrations | Alembic |
| Money | `Decimal` in Python, `NUMERIC`/`DECIMAL` in PostgreSQL — never `float` |
| IDs | UUID public identifiers |
| Time | UTC, timezone-aware timestamps |

Single database, multi-tenant. Every tenant-owned row is keyed by `tenant_id`. Redis is **not**
required. Do not add a cache or queue until a measured need appears (rate limits, forecast jobs).

## Object storage and planned providers

| Capability | Local | Production |
| --- | --- | --- |
| Files / logos / attachments | MinIO (S3 API) | Amazon S3 |
| Email | — | Amazon SES |
| Video | — | Agora |
| Messaging | — | Self-hosted WhatsApp (Go) |
| Assistive AI | — | OpenAI GPT-5.4 Mini |
| Forecast | — | Prophet · XGBoost · LightGBM · Statsmodels |

Integrations live under `app/integrations/`. Business modules never call a vendor SDK.

UAE e-invoicing is **not** implemented in-process. PINT-AE XML, Peppol AS4, and FTA tax-data
reporting belong to an MoF-accredited Accredited Service Provider (ASP). Planned adapters live
under `app/integrations/einvoicing/` (generic ASP default; optional Zoho / Tally adapters).
Plumbit does not become a Peppol Access Point and does not dual-write the ledger into Zoho Books
or TallyPrime.

## Quality and operations

| Tool | Use |
| --- | --- |
| uv | Package and environment management |
| Ruff | Lint and format |
| MyPy | Strict type checking (`app/`) |
| Pytest + pytest-asyncio + httpx | Unit, API, and isolation tests |
| Pre-commit | Local lint / format / type gates |
| Structured JSON logs | `request_id`, `tenant_id`, `user_id`; CloudWatch in production |

OpenAPI snapshots for review live under `docs/openapi/`, generated from the live FastAPI app.

## Frontend (sibling repo)

Next.js App Router on AWS Amplify in production; `next dev` locally. The UI talks to this API
only. It holds no database connection and no ASP credentials.

## Deployment topology

```text
Internet → AWS Amplify (Next.js)
              → API Gateway → Lambda (FastAPI)
                    ├── Amazon RDS PostgreSQL
                    ├── Amazon S3
                    ├── Amazon SES
                    ├── Agora
                    ├── WhatsApp Go (self-hosted)
                    ├── OpenAI GPT-5.4 Mini
                    ├── Forecast ML
                    └── MoF-accredited ASP (e-invoicing; out of process)
```

Local:

```text
Next.js → Uvicorn FastAPI → PostgreSQL + MinIO
```

Health: `GET /health`, `/health/live`, `/health/ready`. Readiness checks PostgreSQL. Do not
require Redis.
