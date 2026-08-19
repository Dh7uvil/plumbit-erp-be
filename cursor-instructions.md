# Cursor Instructions — Plumbit ERP Backend

You are working on a production-grade multi-tenant ERP backend built with FastAPI, PostgreSQL,
SQLAlchemy 2.x, Alembic and Pydantic v2.

Follow the project's architecture and guardrails strictly. ERP financial, inventory and
tenant-isolation rules have higher priority than convenience. Do not bypass these rules even if
doing so makes implementation easier.

## Architecture

```text
Module Router → Service → Repository → SQLAlchemy → PostgreSQL
```

Keep the ERP modular, but do not prematurely turn it into microservices. This is a
well-structured modular monolith: module boundaries, the service and repository layers, events,
integrations, tenant isolation and the authorization model should be strong enough that an
individual module can later be extracted if scale or organizational needs justify it.

## Module map

Modules sit directly under `app/`, with shared building blocks in `app/common/`. Each slice owns
its own `router.py`, `service.py`, `repository.py`, `schemas.py`, `models.py` and
`dependencies.py`.

```text
app/
├── router.py                     mounts every module router under /api/v1
├── core/  db/
├── common/                       models/ schemas/ repositories/ services/ dependencies/ utils/
├── users_management/             auth, users, roles, permissions, tenants
├── erp/                          quotation, sales, purchase_invoices, purchase_orders,
│                                 accounting, logistics, exchange_rates
├── inventory_management/         products, categories, warehouses, stock, transfers, adjustments
├── crm/                          leads, customers, contacts, opportunities, activities
├── communication_service/        email, whatsapp, chat, meetings
├── notifications_service/        notifications, templates, delivery
├── integrations/                 third-party providers only
└── workers/                      background jobs
```

Directories are `snake_case` because Python packages cannot contain hyphens. Modules are a code
concept only — they never appear in the URL, which is a flat set of hyphenated plural resources
(`app/erp/purchase_invoices/` → `/api/v1/purchase-invoices`).

## Detailed instruction files

Read the relevant file before working in that area — each one is the authority for its topic.

| File | Use it when |
| --- | --- |
| [adding-a-new-module](.github/instructions/adding-a-new-module.instructions.md) | Creating a module or feature slice; module registry, folder layout, layer responsibilities, naming |
| [api-design-and-versioning](.github/instructions/api-design-and-versioning.instructions.md) | Designing endpoints, responses, errors, pagination, filtering, sorting, OpenAPI |
| [backend-domain-boundaries](.github/instructions/backend-domain-boundaries.instructions.md) | Tenancy, authorization, module ownership, integrations, financial and workflow invariants |
| [configuration-and-environment](.github/instructions/configuration-and-environment.instructions.md) | Settings, secrets, environments, security defaults, caching, storage, deployment |
| [logging-and-observability](.github/instructions/logging-and-observability.instructions.md) | Structured logs, audit trails, health checks, performance guardrails |
| [migration-and-schema-discipline](.github/instructions/migration-and-schema-discipline.instructions.md) | Model changes, Alembic migrations, indexes, soft deletes, UUIDs |
| [pull-request-and-code-review](.github/instructions/pull-request-and-code-review.instructions.md) | Branching, commits, PR content, review checklist, non-negotiables |
| [testing-and-quality-gates](.github/instructions/testing-and-quality-gates.instructions.md) | Test layers, mandatory ERP test cases, tooling, CI pipeline |

## Core rules

- Keep routers thin. Put business logic in services. Put database access in repositories.
- Put every feature in the module that owns it; a slice keeps its router, service, repository,
  schemas, models and dependencies together.
- `app/common/` holds only what several modules need, never module business logic.
- A module talks to another module through its service — never through its models or repositories.
- Never expose SQLAlchemy models directly; use Pydantic schemas for API contracts.
- Every tenant-owned record must be tenant isolated. Never trust `tenant_id` from the client —
  always derive tenant context from the authenticated user.
- Enforce permission-based authorization at the API/service boundary.
- Use UUIDs for public entity IDs.
- Use `Decimal` for financial calculations. Store timestamps in UTC.
- Use soft deletion where appropriate. Never delete posted financial transactions.
- Never allow invalid workflow status transitions.
- Use database transactions for multi-step business operations; do not call `commit()` inside
  repositories.
- Use Alembic for every schema change. Never modify an already deployed migration.
- Use background workers for long-running operations.
- Keep third-party integrations under `app/integrations/`; never call external providers
  directly from business modules.
- Centralize error handling and use consistent API responses.
- Paginate collection endpoints. Use allowlists for sorting and filtering fields.
- Prevent N+1 queries and add appropriate database indexes.
- Maintain audit logs for important changes. Never log credentials, tokens or secrets, and
  never commit secrets.
- Never introduce a new dependency unless existing dependencies cannot solve the problem.
- Reuse existing utilities and services; do not duplicate functionality.
- Do not over-engineer simple requirements — prefer simple, maintainable implementations.
- Maintain backward compatibility unless a breaking change is explicitly requested.

## Before implementing any feature

1. Inspect the existing implementation.
2. Identify the correct module.
3. Identify related models.
4. Identify existing services.
5. Identify existing repositories.
6. Identify existing schemas.
7. Identify existing permissions.
8. Identify tenant isolation requirements.
9. Identify audit requirements.
10. Identify transaction requirements.
11. Implement the smallest clean solution.
12. Add or update tests.
13. Update the Alembic migration if the schema changes.
14. Verify linting and type checking.

## Before modifying a database model

Check existing relationships, existing migrations, tenant requirements, indexes, foreign keys,
cascade behavior and soft-delete requirements — then generate an Alembic migration.

## Before creating an endpoint

Verify authentication, authorization, tenant isolation, validation, pagination, filtering,
sorting, error handling, audit logging and tests.

## Security posture

Treat every request as untrusted. Never trust any of these from the client:

```text
tenant_id  user_id  role  permission  resource ownership
file type  file name  financial values  status transitions
```

Validate everything on the backend.

## Non-negotiable guardrails

```text
1.  Never bypass authentication.
2.  Never bypass tenant isolation.
3.  Never trust tenant_id from the frontend.
4.  Never bypass authorization checks.
5.  Never put business logic inside routers.
6.  Never expose SQLAlchemy models directly.
7.  Never build raw SQL from user input.
8.  Never store passwords in plain text.
9.  Never commit secrets.
10. Never use float for financial calculations.
11. Never silently modify posted financial transactions.
12. Never physically delete critical financial records.
13. Never allow arbitrary status transitions.
14. Never perform large operations synchronously.
15. Never allow unbounded list queries.
16. Never directly couple ERP modules to third-party providers.
17. Never allow AI to silently modify critical ERP data.
18. Never modify deployed Alembic migrations.
19. Never log credentials or tokens.
20. Never allow one tenant to access another tenant's data.
```

## System overview

```text
                         ┌────────────────────┐
                         │      Frontend      │
                         │   Next.js / React  │
                         └─────────┬──────────┘
                                   ▼
                         ┌────────────────────┐
                         │     FastAPI API    │
                         └─────────┬──────────┘
                ┌──────────────────┼──────────────────┐
                ▼                  ▼                  ▼
          Authentication      Authorization      Tenant Context
                └──────────────────┼──────────────────┘
                                   ▼
                         ┌────────────────────┐
                         │      Modules       │
                         │  users_management  │
                         │  erp               │
                         │  inventory_        │
                         │    management      │
                         │  crm               │
                         │  communication_    │
                         │    service         │
                         │  notifications_    │
                         │    service         │
                         └─────────┬──────────┘
                         ┌─────────▼──────────┐
                         │    Repositories    │
                         └─────────┬──────────┘
                         ┌─────────▼──────────┐
                         │    SQLAlchemy      │
                         └─────────┬──────────┘
                         ┌─────────▼──────────┐
                         │    PostgreSQL      │
                         │   Single Database  │
                         │   Multi-Tenant     │
                         └────────────────────┘

External Integrations          Background Processing

FastAPI                        FastAPI
  ├── AWS S3                     ▼
  ├── AWS SES                  Queue / Redis
  ├── WhatsApp Provider          ▼
  ├── Calendar Provider        Workers
  ├── Video Provider             ├── Emails         ├── Exports
  └── AI Provider                ├── Notifications  ├── Reports
                                 ├── Imports        └── AI Forecasting
```
