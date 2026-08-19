---
description: Centralized configuration, secrets handling, environment separation, security defaults, caching, storage and deployment topology.
applyTo: "app/core/**,.env.example,Dockerfile,docker-compose.yml,alembic.ini,pyproject.toml"
---

# Configuration and Environment

## Centralized configuration

All configuration lives in `app/core/config.py`. Do not scatter `os.getenv` calls throughout
the project — modules import the settings object.

Configuration covers:

```text
Application  Database  Authentication  Storage  Email  WhatsApp
AWS  Redis  Workers  External APIs  Feature Flags
```

## Secrets

Never commit `.env`, passwords, API keys, JWT secrets, database credentials, AWS credentials
or WhatsApp credentials. Use environment variables or a secrets manager.

`.env.example` contains placeholders only, never real values:

```env
DATABASE_URL=
JWT_SECRET=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
```

## Environment separation

Maintain four environments: Development, Testing, Staging and Production. Never use production
credentials locally, and never point automated tests at production.

## Security defaults

These are mandatory, not optional hardening:

```text
HTTPS in production            Input validation           Secure headers
Secure password hashing        SQL injection protection   Auth on protected APIs
JWT expiration                 File upload validation     Authorization on resources
Refresh-token rotation         MIME/type validation       Tenant isolation
Rate limiting on sensitive     Maximum upload sizes       Audit logging
  endpoints
CORS allowlist
```

CORS origins, rate limits and maximum upload sizes are configuration values, not hardcoded
constants scattered in routers.

## File uploads and storage

Never trust the supplied filename, extension or MIME type. Validate file size, extension and
the actual detected content type.

Store uploaded files outside the application filesystem — use object storage such as S3 — and
serve private documents through signed URLs.

## Date and time

Store all timestamps in UTC and use timezone-aware datetime objects. Convert to a local
timezone only at the presentation/API boundary. Never rely on server local time.

## Caching

Use Redis only where caching provides measurable value: permissions, configuration, the current
day's exchange rate, dashboard summaries, frequently accessed reference data, rate limiting and
sessions.

Cache is never the source of truth for financial or inventory records.

## Technology stack

```text
Backend:          Python 3.13.x, FastAPI, Uvicorn, Pydantic v2
Database:         PostgreSQL, SQLAlchemy 2.x, Alembic
Authentication:   JWT, secure password hashing
Caching / Queue:  Redis, Celery / ARQ / equivalent worker system
Testing:          Pytest, HTTPX
Code Quality:     Ruff, MyPy, Pre-commit
Infrastructure:   Docker, AWS
Storage:          Amazon S3
Email:            Amazon SES
Messaging:        WhatsApp provider
Observability:    Structured logging, CloudWatch / equivalent monitoring
```

Do not introduce a new dependency unless the existing ones cannot solve the problem.

## Deployment topology

```text
Internet → Load Balancer / API Gateway → FastAPI
                                           ├── PostgreSQL
                                           ├── Redis
                                           ├── Object Storage
                                           └── Background Workers
```

Run separate worker processes per workload: emails, notifications, imports, exports, reports,
AI and scheduled jobs.
