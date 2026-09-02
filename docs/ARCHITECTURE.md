# Plumbit ERP architecture

System design for a multi-tenant UAE ERP: a FastAPI modular monolith, a Next.js UI on AWS Amplify, and FastAPI on AWS Lambda behind API Gateway.

This document describes **today’s local implementation** and the **target AWS deployment**. It does not propose premature microservices. Module boundaries stay strong enough that a slice can be extracted later if a team or load profile justifies it.

Diagrams: [plumbit-erp-architecture.drawio](plumbit-erp-architecture.drawio) (context, HLD, LLD, modules, request, workflow, local vs prod, ERP controls), [plumbit-erp-erd.drawio](plumbit-erp-erd.drawio) (data model by domain), [plumbit-erp-erd-full.drawio](plumbit-erp-erd-full.drawio) (full schema, one canvas). Stack: [TECH_STACK.md](TECH_STACK.md).

---

## 1. Goals

- Multi-tenant ERP for UAE trading (VAT, emirates as place of supply, AED as the seeded base currency).
- API-first: FastAPI owns validation, tenancy, and workflow.
- Extractable modules: a module talks to another module only through its **service**.
- Financial and inventory invariants outrank convenience: `Decimal` money, locked document numbers, no invalid status jumps, no silent edits to posted transactions, tenant isolation on every query.
- Scale with Lambda concurrency and RDS, not by splitting the monolith.

Non-negotiables: [`cursor-instructions.md`](../cursor-instructions.md) and [backend-domain-boundaries.instructions.md](../.github/instructions/backend-domain-boundaries.instructions.md).

---

## 2. C4 context

```text
  Users (browser)
        │
  AWS Amplify          Next.js product UI
        │
  API Gateway
        │
  AWS Lambda           FastAPI /api/v1
        ├── Amazon RDS PostgreSQL
        ├── Amazon S3
        ├── Amazon SES
        ├── Agora                  video calls
        ├── WhatsApp (Go, self-hosted)
        ├── OpenAI GPT-5.4 Mini
        └── Forecast ML            Prophet · XGBoost · LightGBM · Statsmodels
```

| Person / system | Role |
| --- | --- |
| Tenant users | Staff in a Plumbit organization. They use the Amplify-hosted UI only. |
| AWS Amplify | Hosts Next.js. Locally this is `next dev`; production is Amplify. |
| API Gateway | Public HTTPS API. Forwards to Lambda. |
| AWS Lambda | Runs the same FastAPI app as local Uvicorn. |
| Amazon RDS PostgreSQL | System of record. One database; tenant rows keyed by `tenant_id`. |
| Amazon S3 | Attachments and logos. MinIO locally, same client. |
| Amazon SES | Transactional email. |
| Agora | Real-time video / voice. |
| Self-hosted WhatsApp (Go) | Messaging through a Free Go server you operate. |
| OpenAI GPT-5.4 Mini | Assistive AI. Never silently writes ledger or stock. |
| Forecast ML | Batch/on-demand forecasts; feature-flagged. |

Vite `:5173` is a Figma prototype allowed by CORS. It is not the product frontend.

---

## 3. Containers

### Today (local)

```text
Browser :3000  →  Next.js (rewrites + BFF cookies)
                     │
                     ▼
               FastAPI :8000 (uvicorn --reload)
                     ├── PostgreSQL
                     └── MinIO :9000
```

Secrets come from `.env`. Tests use `.env.test` and `plumb_it_test`.

### Target (HLD)

```text
Internet → AWS Amplify (Next.js)
              → API Gateway
                → Lambda (FastAPI)
                      ├── RDS PostgreSQL
                      ├── S3
                      ├── SES
                      ├── Agora
                      ├── WhatsApp Go (self-hosted)
                      ├── OpenAI GPT-5.4 Mini
                      └── Forecast ML
```

Ops: Secrets Manager for JWT, DB, provider keys; CloudWatch for JSON logs (`request_id`, `tenant_id`, `user_id`, method, path, status, duration).

Lambda is a new host for the existing ASGI app. Domain modules do not change because the process is Lambda.

Health: `GET /health`, `/health/live`, `/health/ready` (PostgreSQL today). Wire `/health/ready` as the Gateway/Lambda health check.

---

## 4. Internal layers (LLD)

Request path inside Lambda:

```text
API Gateway event
  → Lambda adapter (ASGI)
  → RequestContextMiddleware (x-request-id)
  → CORSMiddleware
  → /health*  or  /api/v1/...
  → slice router (thin)
  → service (rules, transactions, audit)
  → repository (tenant-scoped SQL)
  → RDS PostgreSQL
```

Integrations are called only from services, via `app/integrations/`:

```text
storage    → S3
email      → SES
whatsapp   → self-hosted Go server
video      → Agora
ai         → OpenAI GPT-5.4 Mini
forecast   → Prophet / XGBoost / LightGBM / Statsmodels
einvoicing → MoF-accredited ASP (planned; not in-process)
```

| Package | Owns |
| --- | --- |
| `app/main.py` | FastAPI app, middleware, OpenAPI tags, lifespan. |
| `app/router.py` | Single `/api/v1` mount. |
| `app/core/` | Config, JWT, permissions, exceptions, logging, enums. |
| `app/db/` | Engine, session, mixins, seeds. Services call `transaction()`. |
| `app/common/` | Envelope, pagination, `BaseRepository`, tenant/auth/permission deps, audit, attachments. No module business rules. |
| Feature modules | Identity, CRM, inventory, ERP — each slice has router, service, repository, schemas, models, dependencies. |
| `app/integrations/` | Third-party adapters only. Today: `storage/`. Planned: email, WhatsApp, video, AI, forecast, `einvoicing/` (ASP adapters). |
| `app/workers/` | Not created. Forecast, mail/import/PDF, and e-invoice submit/poll/inbound webhook belong here (or a second Lambda). |
| `app/cli/` | `create-tenant`, `seed-tenants`, `generate-jwt-secret`. |
| `alembic/` | Schema history. |
| `tests/` | Unit, API, and isolation tests. |

Identity lives in `app/auth/`. URLs never include the module name: `app/erp/quotation/` → `/api/v1/quotations`.

---

## 5. Module map

Solid = implemented. Dashed in draw.io = planned.

| Top-level | Implemented slices | API examples | Planned slices |
| --- | --- | --- | --- |
| Identity (`app/auth/`) | tenants, auth, users, roles, permissions, branches, departments, employees (nested), audit logs | `/tenants`, `/auth/login`, `/users`, `/roles` | tenant operational settings (`allow_negative_stock`, `lock_date`, `hard_lock_date`) as columns |
| CRM (`app/crm/`) | customers, contacts | `/customers`, `/contacts` | leads, opportunities, activities |
| Inventory (`app/inventory_management/`) | units, categories, products, price lists, warehouses | `/units`, `/products`, `/warehouses` | stock, transfers, adjustments, GRN, delivery notes, sales returns |
| ERP (`app/erp/`) | currencies, exchange rates, taxes, payment terms, terms templates, document sequences, suppliers, quotations | `/quotations`, `/suppliers`, `/exchange-rates` | sales orders, sales invoices, credit notes, customer payments, purchase orders, purchase invoices, debit notes, supplier payments, logistics, journals / AR / AP, einvoicing status APIs |
| Common | attachments | `/attachments` | — |
| `integrations` | storage | — | email, WhatsApp, video, AI, forecast, `einvoicing/` ASP adapters |
| `communication_service` | — | — | email, WhatsApp, chat, meetings (Agora) |
| `notifications_service` | — | — | in-app / email / WhatsApp, templates, delivery |
| `workers` | — | — | email, imports, PDF, reports, Forecast ML, einvoice submit / poll / inbound webhook |

Permissions: `identity.*`, `crm.*`, `inventory.*`, `erp.*` (for example `identity.user.read`, `erp.quotation.approve`, `erp.einvoice.submit`). Do not use `users.*`.

Workflow documents must return `available_actions`. Posting is `POST /{resource}/{id}/post`, not a side effect of PATCH. E-invoicing adapters live under `app/integrations/einvoicing/`; status fields live on the ERP document. Zoho/Tally are optional ASP providers, not a second ledger.

---

## 6. Cross-module rule

A module never imports another module’s models or repositories. It calls the owning **service**.

```text
Bad:   crm/customers/service.py  →  inventory_management/products/models.py
Good:  erp/quotation/service.py  →  inventory product service
```

Orchestrators live in the module that owns the process (for example future `erp/sales/`), not in `app/common/`. Events are for side effects (email, WhatsApp, forecasts) after the atomic commit.

```text
erp/sales → notifications_service → WhatsApp adapter → self-hosted Go server
erp/sales → communication_service → Agora
inventory → forecast worker → Prophet / XGBoost / LightGBM / Statsmodels
```

---

## 7. Tenancy, RBAC, audit, documents, money, workflow

### Tenancy

Single RDS database. `TenantScopedMixin` puts indexed `tenant_id` on every owned table. `BaseRepository` always adds `tenant_id == …` and `deleted_at IS NULL`. Tenant comes from the authenticated user, never from a client body or header.

### Authentication

Local: Next BFF sets httpOnly cookies `pb_access` / `pb_refresh`. Production: Amplify-hosted Next.js can keep that BFF, then call API Gateway with the Bearer token. FastAPI still validates JWT, active user, active tenant, and permissions.

### Authorization

`module.resource.action` at the API/service boundary. Frontend checks are UX only.

### Audit

Append-only `audit_logs`: tenant, user, action, module, entity, old/new values, IP, user agent.

### Document numbers, money, workflow

Locked sequences (`lock_for_allocate`). `Decimal` only. Quotation VAT in `app/erp/quotation/totals.py`. Status machines in `app/erp/quotation/workflow.py`.

### Immutability and double-entry

Posted rows are never overwritten. An AED 1,000 July invoice is not edited to AED 800 in August. The user posts a credit note or reversal in the **open** period. That is the ledger.

### Negative stock

Tenant setting `allow_negative_stock` (default false), documented as a first-class column when implemented — not a JSONB extra. When false, dispatch/sale aborts if physical qty is insufficient: *Post the purchase invoice / GRN first* (`INVENTORY_INSUFFICIENT_STOCK`). The inventory service checks this under `SELECT FOR UPDATE` in the same transaction as the movement.

### Period lock

Tenant `lock_date` (non-advisers) and `hard_lock_date` (everyone), first-class columns when implemented. Create/edit/delete of dated vouchers is rejected when `document_date <= lock` (`PERIOD_LOCKED`). Advancing the lock is refused while any warehouse has negative on-hand (`PERIOD_LOCK_BLOCKED_NEGATIVE_STOCK`). AI may flag issues before close; it does not set the lock.

### Invoice posting

`DRAFT` save does not touch stock, AR, tax or GL. Explicit Confirm/Post (or a permissioned batch) moves `DRAFT → POSTED` and, in one transaction, updates inventory, tax, AR/AP and GL. UI "Sent" / "Approved" maps to `POSTED`. After commit, e-invoice submit is an outbox/worker job to an MoF-accredited ASP; posting does not wait on Peppol.

### UAE VAT and e-invoicing

TRN when `REGISTERED`, place of supply from emirate, tax categories `STANDARD` / `ZERO_RATED` / `EXEMPT` / `OUT_OF_SCOPE`. PINT-AE completeness (Peppol IDs, UQC, allowance/charge reason codes) is required before `submit_einvoice` appears in `available_actions`. Plumbit does not generate Peppol AS4 or become an ASP.

---

## 8. Request path

```text
Production
  Browser → Amplify (Next.js)
         → API Gateway /api/v1/...
         → Lambda → FastAPI
         → tenant + permission
         → service → tenant-scoped repository
         → { success, data, message, meta }

Local
  Browser → Next.js rewrite or BFF
         → Uvicorn FastAPI
         → same layers as above
```

---

## 9. Scalability path (no rewrite)

1. **Scale HTTP with Lambda concurrency**, not more Uvicorn processes. Put **RDS Proxy** in front of RDS so each concurrent Lambda does not open a raw connection.
2. **Scale work** on a second Lambda (or worker) for SES, WhatsApp, imports, PDFs, and Forecast ML. The request Lambda enqueues; it does not fit Prophet/XGBoost into the user request.
3. **Scale data later:** read replicas, then partition hot tables by `tenant_id` / `created_at`.
4. **Extract a service last** (notifications, communication, forecast workers) when a team or load profile is isolated.

Keep the ERP modular. Do not turn it into microservices early.

---

## 10. What is not built yet

- Amplify, API Gateway, and Lambda packaging.
- SES, Agora, WhatsApp Go adapter, OpenAI, Forecast ML, `app/workers/`.
- Stock movements with `allow_negative_stock`, period lock dates as tenant columns, and DRAFT → POSTED invoices.
- `Idempotency-Key` / `If-Match` on invoice post, payments, and stock movements.
- UAE e-invoicing ASP adapter, PINT-AE completeness fields, inbound e-bill drafts.
- Splitting PostgreSQL per tenant.

Quotations already return `available_actions`, `version`, `is_posted` (always false), and `document_number` / `document_date` aliases. PATCH and workflow verbs require `If-Match` (or body `version`); a mismatch is `DOCUMENT_STALE`. Planned ledger documents still need the same contract when they are built.

When those land, update this file and the matching draw.io page (solid vs dashed).
