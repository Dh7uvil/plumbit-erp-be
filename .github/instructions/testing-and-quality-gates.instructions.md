---
description: Test layers, mandatory ERP test cases, tenant-isolation tests, tooling and the CI pipeline.
applyTo: "tests/**,pyproject.toml,Makefile"
---

# Testing and Quality Gates

## Test layout

Tests mirror the module packages under `app/`, so a slice's tests are found by following the
same path.

```text
tests/
├── conftest.py
├── unit/         users_management/ erp/ inventory_management/ crm/
│                 communication_service/ notifications_service/ common/
├── integration/  (same module tree)
└── api/          (same module tree)
```

For example, `app/erp/purchase_invoices/service.py` is tested by
`tests/unit/erp/purchase_invoices/test_service.py` and
`tests/api/erp/purchase_invoices/test_routes.py`.

## Test layers

```text
Unit Tests                     business rules in services, pure helpers
Integration Tests              service + repository + database together
API Tests                      full request flow through FastAPI
Security Tests                 authn/authz, input validation, injection attempts
Multi-Tenant Isolation Tests   cross-tenant access is impossible
```

Unit tests may mock repositories and integrations. Integration and API tests run against a
real PostgreSQL test database — never against production.

## Mandatory test cases

Every one of these must be covered:

```text
User cannot access another tenant
User cannot access an unauthorized module
User cannot modify another user's restricted data
Posted accounting transaction cannot be deleted
Completed workflow cannot return to draft
Invalid imports are rejected
Duplicate document numbers cannot occur
Concurrent stock updates remain consistent
```

## The tenant isolation test

Every tenant-isolated endpoint gets a test shaped like this:

```text
Tenant A → Customer A
Tenant B → Customer B

Tenant A user requests Customer B  →  403 / 404
```

The response must never contain Tenant B's data, and must not leak its existence through a
distinguishable error message or timing difference. This test is not optional for any new
tenant-owned endpoint.

## Tooling

```text
Ruff  Black  MyPy  Pytest  Pre-commit
```

Pre-commit hooks run lint, format and type checks locally so CI is not the first place a
failure is discovered.

## CI pipeline

```text
Push → Lint → Format Check → Type Check → Unit Tests
     → Integration Tests → Security Checks → Build
```

A red pipeline blocks merge. Do not skip, xfail or delete a failing test to get a green build —
fix the behavior or the test's premise.

## Writing tests for a new feature

- Test the business rule in the service, not through the router, when the rule is the subject.
- Cover the failure paths: missing permission, wrong tenant, invalid status transition,
  insufficient stock, duplicate document number.
- Assert on the application error code, not just the HTTP status.
- Use factories/fixtures in `conftest.py` rather than hand-built objects repeated per test.
- Keep tests independent and order-free; each test creates and cleans up its own data.
