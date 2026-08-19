---
description: Branching, commit format, pull request expectations and the review checklist including non-negotiable guardrails.
applyTo: "**"
---

# Pull Request and Code Review

## Branches

```text
main  develop  feature/*  bugfix/*  hotfix/*  release/*
```

## Commit format

```text
feat: add sales order workflow
fix: prevent cross-tenant customer access
refactor: simplify inventory service
test: add tenant isolation tests
docs: update accounting guidelines
chore: update dependencies
```

## Never commit

```text
.env  credentials  private keys  database dumps  large generated files
```

If a secret is committed, rotate it — removing the file is not sufficient.

## Pull request expectations

A pull request should be the smallest clean change that delivers the requirement. It states
what changed and why, calls out any schema change and its migration, and lists the new or
updated tests. Breaking API changes are flagged explicitly; otherwise backward compatibility
is assumed.

Before requesting review, run the local gates: Ruff, Black, MyPy and Pytest.

## Review checklist

**Layering**
- Routers stay thin; no business logic, no queries in routers.
- Business rules live in services; database access lives in repositories.
- No SQLAlchemy model is exposed through an API response.
- Dependency direction holds: API → Services → Repositories → Models → Database.

**Tenancy and authorization**
- Every tenant-owned query is scoped by `tenant_id`.
- `tenant_id` comes from authenticated context, never from the client.
- Every endpoint has an explicit permission check.

**Data correctness**
- `Decimal` used for money; no `float` in financial paths.
- Timestamps stored in UTC.
- Status transitions validated against the allowed state machine.
- Posted financial records are not updated or deleted.
- Document numbers generated through a concurrency-safe mechanism.

**API surface**
- Consistent response envelope and application error codes.
- Pagination on list endpoints with an enforced maximum page size.
- Sorting and filtering use allowlists; no raw SQL from user input.
- OpenAPI summary, description, schemas, status codes and permissions declared.

**Schema**
- Alembic migration included and reviewed for any model change.
- No previously deployed migration was modified.
- Indexes added for new filter/sort columns.

**Operational**
- Structured logs carry `request_id`, `tenant_id` and `user_id`; no credentials or tokens logged.
- Audit log written for state changes.
- Long-running work moved to background workers.
- Third-party calls go through `app/integrations/`, not business modules.

**Quality**
- Unit, integration, API and tenant-isolation tests added or updated.
- No duplicated functionality; existing utilities and services reused.
- No new dependency unless existing ones genuinely cannot solve the problem.
- Not over-engineered — simple and maintainable wins.

## Non-negotiable guardrails

A pull request that violates any of these is rejected regardless of its other merits.

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
