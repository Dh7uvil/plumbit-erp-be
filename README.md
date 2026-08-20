# Plumbit ERP Backend

Foundation for a production-oriented, multi-tenant ERP API built with Python 3.13, FastAPI,
Pydantic v2, async SQLAlchemy 2.x, PostgreSQL, and Alembic.

## Project layout

```text
app/
├── auth/       Identity, organization settings, and audit-log APIs
├── core/       Configuration and cross-cutting application primitives
├── db/         Async SQLAlchemy and Alembic integration
└── common/     Shared schemas, dependencies, repositories, and utilities
alembic/        Database migration environment and revisions
docs/openapi/   Per-tag OpenAPI snapshots generated from the live FastAPI app
tests/          Unit and API tests
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

Start the API after the application entry point is available:

```bash
uv run uvicorn app.main:app --reload
```

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
