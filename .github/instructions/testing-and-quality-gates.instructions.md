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
├── unit/         auth/ erp/ inventory_management/ crm/
│                 communication_service/ notifications_service/ common/ integrations/
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
Posted accounting transaction cannot be deleted or overwritten in place
Credit note does not mutate the original posted row
Draft invoice does not move stock or hit AR / tax / GL
Posted invoice deducts stock and posts ledgers in one transaction
Double-post with the same Idempotency-Key is idempotent
Stale If-Match / version on PATCH or post is DOCUMENT_STALE
Sale / dispatch blocked when allow_negative_stock is false and qty is insufficient
Concurrent stock updates remain consistent (SELECT FOR UPDATE)
Voucher dated on or before lock_date is rejected (PERIOD_LOCKED)
Period lock is refused while any warehouse has negative on-hand
VAT place-of-supply / REGISTERED-requires-TRN rules hold
Completed / posted workflow cannot return to draft
available_actions matches the service state machine, not client input
Draft is never submitted to an ASP
Post without a reachable ASP still posts the local ledger
Rejected e-invoice is not editable; credit-note path is required
Inbound e-invoice webhook creates a DRAFT purchase invoice and does not post AP
EinvoiceProvider is mockable in tests
Invalid imports are rejected
Duplicate document numbers cannot occur
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
  insufficient stock, closed period, posting a draft twice, duplicate document number,
  stale If-Match, ASP down after post, inbound webhook without a valid signature.
- Assert on the application error code, not just the HTTP status.
- Use factories/fixtures in `conftest.py` rather than hand-built objects repeated per test.
- Keep tests independent and order-free; each test creates and cleans up its own data.
