# Plumbit ERP Backend

Foundation for a production-oriented, multi-tenant ERP API built with Python 3.13, FastAPI,
Pydantic v2, async SQLAlchemy 2.x, PostgreSQL, and Alembic.

## Project layout

```text
app/
├── auth/                    Identity, organization, and audit-log APIs
├── common/                  Shared schemas, dependencies, attachments, and utilities
├── core/                    Configuration and cross-cutting application primitives
├── db/                      Async SQLAlchemy and Alembic integration
├── erp/                     Quotations, accounting, and exchange rates
├── crm/                     Customers and contacts
├── inventory_management/    Units, categories, products, price lists, warehouses
├── integrations/            S3-compatible storage (MinIO locally, AWS S3 in production)
└── router.py                Flat /api/v1 resource mount
alembic/                     Database migration environment and revisions
docs/openapi/                Per-tag OpenAPI snapshots generated from the live FastAPI app
tests/                       Unit and API tests
```

## Local setup

Install [uv](https://docs.astral.sh/uv/), then run:

```bash
uv sync --dev
cp .env.example .env
```

Fill `.env` with local development credentials. Never commit that file or use production
credentials locally.

Generate the `JWT_SECRET` value with:

```bash
uv run generate-jwt-secret --env
```

Provision a tenant (ISO currencies, VAT, UOMs, MAIN warehouse, and the QUO sequence
are seeded in the same transaction):

```bash
uv run create-tenant
```

Backfill the ISO 4217 catalog onto tenants that already exist (idempotent; skips
codes that are present):

```bash
uv run seed-tenants
uv run seed-tenants --tenant-id <uuid>
uv run seed-tenants --tenant-code <code>
```

Object storage uses one S3 client everywhere. For local development, run MinIO and point
the API at it:

```bash
docker compose up -d
```

Then set in `.env`:

```env
S3_ENDPOINT_URL=http://127.0.0.1:9000
S3_BUCKET_NAME=plumbit
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin
AWS_REGION=us-east-1
```

Leave `S3_ENDPOINT_URL` unset in production so boto3 talks to AWS S3. The MinIO console is at
http://127.0.0.1:9001 (`minioadmin` / `minioadmin`). Organization logos are uploaded with
`POST /api/v1/tenants/current/logo` (not `/attachments`); authenticated and public tenant
responses include a short-lived `logo_url` for display.

Start the API after the application entry point is available:

```bash
uv run uvicorn app.main:app --reload
```

## Tests

Pytest always loads `.env.test` and will refuse to run unless `ENV=testing` and
`DATABASE_NAME=plumb_it_test`. It never reads `.env` and must never target the development
database.

```bash
createdb plumb_it_test   # or CREATE DATABASE plumb_it_test;
cp .env.test.example .env.test
```

Fill `.env.test` with local credentials (a dedicated JWT secret is fine). Then apply migrations
to the test database and run the suite:

```bash
ENV=testing uv run alembic upgrade head
uv run pytest
```

`ENV=testing` makes Settings load `.env.test` so Alembic targets `plumb_it_test` rather than
the database in `.env`.

## Quality checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
```

## Database migrations

Create schema changes through Alembic; never edit a migration that has already been deployed:

```bash
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

Review every generated revision for tenant boundaries, constraints, indexes, and unintended
destructive operations before applying it.
