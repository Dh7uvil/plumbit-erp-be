# Cursor Instructions — Plumbit ERP Backend

You are working on a production-grade multi-tenant UAE trading ERP backend built with FastAPI,
PostgreSQL, SQLAlchemy 2.x, Alembic and Pydantic v2.

The product scope is Zoho Books + Inventory + CRM / Odoo Sales, Purchase, Inventory, Accounting,
CRM: quotes, orders, invoices, GRN, credit/debit notes, payments, stock, journals, UAE VAT, and
UAE e-invoicing through third-party Accredited Service Providers (ASPs). Manufacturing, POS, full
payroll, e-commerce, projects/timesheets, recurring invoices, and banking/PDC are out of scope.

Follow the project's architecture and guardrails strictly. ERP financial, inventory, tenant-isolation
and e-invoicing rules have higher priority than convenience. Do not bypass these rules even if
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

Identity lives in `app/auth/`. Do not invent a `users_management` package. Permission prefixes are
`identity.*`, `crm.*`, `inventory.*`, `erp.*`.

Label implemented vs planned so agents do not stub screens or empty OpenAPI tags without an API.

```text
app/
├── router.py                     mounts every module router under /api/v1
├── core/  db/  cli/
├── common/                       models/ schemas/ repositories/ services/ dependencies/
│                                 utils/ attachments/
├── auth/                         Identity: auth, users, roles, permissions, tenants/org-settings,
│                                 branches, departments, employees (nested), audit-logs
│                                 planned: tenant operational settings (negative stock, lock dates)
├── crm/                          implemented: customers, contacts
│                                 planned: leads, opportunities, activities
├── inventory_management/         implemented: units, categories, products, price_lists, warehouses
│                                 planned: stock, stock_transfers, stock_adjustments,
│                                 goods_receipts (GRN), delivery_notes, sales_returns
├── erp/                          implemented: currencies, exchange_rates, taxes, payment_terms,
│                                 terms_templates, document_sequences, suppliers, quotations
│                                 planned: sales_orders, sales_invoices, credit_notes,
│                                 customer_payments, purchase_orders, purchase_invoices,
│                                 debit_notes, supplier_payments,
│                                 accounting (chart_of_accounts, journals, AR, AP),
│                                 logistics (imports, exports, shipments, containers),
│                                 einvoicing (status APIs on sales invoices and credit notes;
│                                 inbound e-bills as draft purchase invoices)
├── integrations/                 implemented: storage/
│                                 planned: email, whatsapp, video, ai, forecast,
│                                 einvoicing/ (ASP adapters only — Zoho, Tally, generic Peppol ASP)
├── communication_service/        planned: email, whatsapp, chat, meetings
├── notifications_service/        planned: notifications, templates, delivery
└── workers/                      planned: imports, exports, reports, PDF, AI,
                                  einvoice submit / poll / inbound webhook
```

Directories are `snake_case` because Python packages cannot contain hyphens. Modules are a code
concept only — they never appear in the URL, which is a flat set of hyphenated plural resources
(`app/erp/purchase_invoices/` → `/api/v1/purchase-invoices`). Resource segments must be unique:
`/credit-notes`, `/debit-notes`, `/customer-payments`, `/supplier-payments`, `/delivery-notes`.

Document-number prefixes: `QUO`, `SO`, `DN` (delivery notes), `INV`, `CN` (credit notes), `PO`,
`GRN`, `BILL` (purchase invoices), `SDN` (debit notes). Prefer a unique prefix per type; URLs
must be unique even if a prefix is shared.

## Detailed instruction files

Read the relevant file before working in that area — each one is the authority for its topic.

| File | Use it when |
| --- | --- |
| [adding-a-new-module](.github/instructions/adding-a-new-module.instructions.md) | Creating a module or feature slice; module registry, folder layout, layer responsibilities, naming |
| [api-design-and-versioning](.github/instructions/api-design-and-versioning.instructions.md) | Designing endpoints, responses, errors, pagination, filtering, sorting, OpenAPI, document contract |
| [backend-domain-boundaries](.github/instructions/backend-domain-boundaries.instructions.md) | Tenancy, authorization, module ownership, VAT, posting, lock/stock, e-invoicing, integrations |
| [configuration-and-environment](.github/instructions/configuration-and-environment.instructions.md) | Settings, secrets, environments, security defaults, caching, storage, ASP credentials, deployment |
| [logging-and-observability](.github/instructions/logging-and-observability.instructions.md) | Structured logs, audit trails, health checks, performance guardrails |
| [migration-and-schema-discipline](.github/instructions/migration-and-schema-discipline.instructions.md) | Model changes, Alembic migrations, indexes, soft deletes, UUIDs, document uniqueness |
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
- Enforce permission-based authorization at the API/service boundary (`identity.*` / `crm.*` /
  `inventory.*` / `erp.*`).
- Use UUIDs for public entity IDs.
- Use `Decimal` for financial calculations. Store timestamps in UTC.
- Use soft deletion where appropriate. Never delete posted financial transactions.
- Never overwrite a posted voucher. Correct it with a credit note, debit note, reversal or
  adjustment in the **open** period (double-entry, immutable history).
- Respect tenant `allow_negative_stock`. When it is off, block dispatch/sale if physical stock
  is insufficient — require GRN / purchase receipt first. Check under `SELECT FOR UPDATE`.
- Respect tenant lock dates. Do not create, edit or delete a voucher dated on or before the lock.
  Refuse to advance a lock while any warehouse is negative.
- Invoices stay `DRAFT` until explicit Confirm/Post. Drafts do not touch stock, AR, tax or GL.
  Posting is `POST /{resource}/{id}/post` (or `/confirm`), never a side effect of PATCH.
- Every workflow document response includes `available_actions`. That list is the only legal
  source of UI buttons.
- UAE VAT: require TRN when `REGISTERED`; place of supply from emirate; never recompute posted tax.
- Posting is local (stock + AR/AP + tax + GL in one transaction). Peppol/FTA exchange is an ASP
  job after commit, via `app/integrations/einvoicing/` and the transactional outbox — never from
  `erp/sales_invoices/service.py`.
- Never allow invalid workflow status transitions.
- Use database transactions for multi-step business operations; do not call `commit()` inside
  repositories.
- Use Alembic for every schema change. Never modify an already deployed migration.
- Use background workers for long-running operations (imports, PDF/print, e-invoice submit/poll).
- Keep third-party integrations under `app/integrations/`; never call external providers
  directly from business modules.
- Centralize error handling and use consistent API responses.
- Paginate collection endpoints. Use allowlists for sorting and filtering fields.
- Prevent N+1 queries and add appropriate database indexes.
- Maintain audit logs for important changes. Never log credentials, tokens or secrets, and
  never commit secrets.
- Feature-flag unfinished modules so they do not appear in OpenAPI as empty stubs.
- Never introduce a new dependency unless existing dependencies cannot solve the problem.
- Reuse existing utilities and services; do not duplicate functionality.
- Do not over-engineer simple requirements — prefer simple, maintainable implementations.
- Maintain backward compatibility unless a breaking change is explicitly requested.

## Before implementing any feature

1. Inspect the existing implementation.
2. Identify the correct module (Identity is `app/auth/`, not `users_management`).
3. Identify related models.
4. Identify existing services.
5. Identify existing repositories.
6. Identify existing schemas.
7. Identify existing permissions (`identity.*` / `crm.*` / `inventory.*` / `erp.*`).
8. Identify tenant isolation requirements.
9. Identify audit, lock-date, negative-stock, posting (DRAFT vs POSTED), VAT and e-invoicing
   requirements.
10. Identify transaction, idempotency and optimistic-concurrency (`version` / `If-Match`) needs.
11. Implement the smallest clean solution.
12. Add or update tests.
13. Update the Alembic migration if the schema changes.
14. Update the OpenAPI snapshot under `docs/openapi/` if the public contract changes.
15. Verify linting and type checking.

## Before modifying a database model

Check existing relationships, existing migrations, tenant requirements, indexes, foreign keys,
cascade behavior and soft-delete requirements — then generate an Alembic migration.

## Before creating an endpoint

Verify authentication, authorization, tenant isolation, validation, pagination, filtering,
sorting, error handling, audit logging, `available_actions` on document responses, and tests.

## Security posture

Treat every request as untrusted. Never trust any of these from the client:

```text
tenant_id  user_id  role  permission  resource ownership
file type  file name  financial values  status transitions
available_actions  einvoice_status
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
13. Never overwrite a posted amount in place — post a credit note / reversal in the open period.
14. Never allow stock below zero when the tenant disallows negative stock.
15. Never mutate a voucher whose date is on or before the tenant lock date.
16. Never hit the ledger or stock from a DRAFT invoice.
17. Never allow arbitrary status transitions.
18. Never perform large operations synchronously.
19. Never allow unbounded list queries.
20. Never directly couple ERP modules to third-party providers.
21. Never allow AI to silently modify critical ERP data. AI may recommend; a user confirms writes.
22. Never modify deployed Alembic migrations.
23. Never log credentials or tokens.
24. Never allow one tenant to access another tenant's data.
25. Never call an Accredited Service Provider from a business module — only via app/integrations/einvoicing/.
26. Never dual-write posted invoices or journals into Zoho Books, TallyPrime, or any ASP ledger.
27. Never implement Peppol AS4, OpenPeppol PKI, or MoF ASP accreditation inside Plumbit.
```

## System overview

Production: AWS Amplify (Next.js) → API Gateway → Lambda (FastAPI) → RDS PostgreSQL, S3,
SES, Agora, self-hosted WhatsApp (Go), OpenAI GPT-5.4 Mini, Forecast ML, MoF-accredited ASP
(e-invoicing, out of process).

Local: Next.js → Uvicorn FastAPI → PostgreSQL + MinIO.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/TECH_STACK.md](docs/TECH_STACK.md).

```text
Users → Amplify → API Gateway → Lambda / FastAPI
                                      ├── RDS PostgreSQL (multi-tenant)
                                      ├── S3
                                      ├── SES · Agora · WhatsApp Go
                                      ├── OpenAI · Forecast ML
                                      └── MoF ASP (PINT-AE / Peppol / FTA)
```
