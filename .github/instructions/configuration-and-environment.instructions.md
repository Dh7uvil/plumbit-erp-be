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
Application  Database  Authentication  Storage  Email  WhatsApp  Agora
AWS Lambda  API Gateway  Amplify  OpenAI  Forecast  Feature Flags
```

## Secrets

Never commit `.env`, passwords, API keys, JWT secrets, database credentials, AWS credentials
or WhatsApp credentials. Use environment variables or a secrets manager.

`.env.example` contains placeholders only, never real values:

```env
DATABASE_HOST=
DATABASE_NAME=
DATABASE_USER=
DATABASE_PASSWORD=
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

Cache is never the source of truth for financial or inventory records. Do not introduce Redis
unless a measured need appears (rate limits, forecast job queue). The target production stack
does not require it.

## Technology stack

Platforms (not application libraries):

```text
Local API:        Python 3.13, FastAPI on Uvicorn
Production API:   AWS Lambda (same FastAPI app) behind API Gateway
Frontend:         Next.js on AWS Amplify (local: next dev)
Database:         PostgreSQL / Amazon RDS (single DB, multi-tenant)
Storage:          MinIO locally, Amazon S3 in production
Email:            Amazon SES
Video:            Agora
Messaging:        self-hosted WhatsApp (Go)
AI:               OpenAI GPT-5.4 Mini (assistive only)
Forecast:         Prophet · XGBoost · LightGBM · Statsmodels
Observability:    Structured JSON logs, CloudWatch in production
```

Do not introduce a new dependency unless the existing ones cannot solve the problem.
Details: [docs/TECH_STACK.md](../../docs/TECH_STACK.md).

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
                    └── Forecast ML
```

Run forecast, mail and import work on a separate Lambda/worker — not inside the user request.
