---
description: How to add a new ERP module or feature — module registry, module-owned folder layout, layer responsibilities, request flow and naming.
applyTo: "app/**"
---

# Adding a New Module

Every ERP feature is added as a self-contained slice inside one of the top-level modules,
following the same layout and the same request flow. Do not invent a new shape for a new module.

## Before writing any code

1. Inspect the existing project structure.
2. Identify the correct top-level module — do not create a new one if the feature belongs to an
   existing module. Identity is `app/auth/`, not `users_management`.
3. Identify existing services, repositories, schemas and common utilities and reuse them.
4. Identify related models and database relationships.
5. Identify the permissions the feature needs (`identity.*` / `crm.*` / `inventory.*` / `erp.*`).
6. Identify tenant isolation, lock-date, negative-stock, posting, VAT and e-invoicing
   requirements.
7. Identify audit, transaction, idempotency and `version` / `If-Match` requirements.
8. Avoid duplicate functionality and unnecessary dependencies.
9. Implement the smallest clean solution. Feature-flag unfinished modules so they do not appear
   in OpenAPI as empty stubs.

## Top-level modules

These are the only top-level modules. Everything belongs to exactly one of them. Label
implemented vs planned so agents do not stub a slice without an API.

| Module | Owns |
| --- | --- |
| `auth` (Identity) | **Implemented:** auth, users, roles, permissions, tenants/org-settings, branches, departments, employees (nested), audit-logs. Attachments in `app/common/attachments/` with `identity.attachment.*`. **Planned:** tenant operational settings (`allow_negative_stock`, `lock_date`, `hard_lock_date`). |
| `erp` | **Implemented:** currencies, exchange_rates, taxes, payment_terms, terms_templates, document_sequences, suppliers, quotations. **Planned:** sales_orders, sales_invoices, credit_notes, customer_payments, purchase_orders, purchase_invoices, debit_notes, supplier_payments, accounting (chart of accounts, journals, AR, AP), logistics, einvoicing **status APIs** (on sales invoices and credit notes; inbound e-bills as draft purchase invoices). |
| `inventory_management` | **Implemented:** units, categories, products, price_lists, warehouses. **Planned:** stock, stock_transfers, stock_adjustments, goods_receipts (GRN), delivery_notes, sales_returns. |
| `crm` | **Implemented:** customers, contacts. **Planned:** leads, opportunities, activities. |
| `communication_service` | **Planned:** email, whatsapp, chat, meetings. |
| `notifications_service` | **Planned:** notifications, templates, delivery status. |

`app/integrations/` is not a business module. It holds provider adapters only (`storage/`
today; planned `email/`, `whatsapp/`, `video/`, `ai/`, `forecast/`, `einvoicing/`). E-invoicing
**adapters** go under `integrations/einvoicing/`. E-invoicing **status APIs** go under `erp/`.

Adding a new top-level module requires explicit justification. If a feature is close to an
existing module's domain, it becomes a slice inside that module instead. Do not add
manufacturing, POS, payroll, or banking slices.

## Repository layout

Match the live tree (`auth/`, `cli/`, `docs/openapi/`). Do not invent `users_management/`.

```text
plumbit-erp-be/
│
├── app/
│   ├── main.py
│   ├── router.py                 mounts every module router under /api/v1
│   ├── health.py
│   │
│   ├── core/                     config.py security.py permissions.py exceptions.py
│   │                             error_handlers.py middleware.py logging.py constants.py enums.py
│   ├── db/                       base.py session.py mixins.py seed.py
│   ├── cli/                      create_tenant.py seed_tenants.py generate_jwt_secret.py
│   │
│   ├── common/                   shared building blocks — no module business logic
│   │   ├── models/               audit_log.py (tenant/user/role live in auth/)
│   │   ├── schemas/              response.py pagination.py filters.py
│   │   ├── repositories/         base.py
│   │   ├── services/             audit.py
│   │   ├── dependencies/         auth.py tenant.py permissions.py pagination.py
│   │   ├── attachments/          identity.attachment.* slice
│   │   └── utils/                datetime.py currency.py validators.py generators.py files.py
│   │
│   ├── auth/                     Identity — router, service, org, audit, catalog
│   ├── erp/
│   │   ├── quotation/
│   │   ├── suppliers/
│   │   ├── exchange_rates/
│   │   ├── accounting/           taxes, payment_terms, terms_templates, document_sequences
│   │   ├── sales_orders/         planned
│   │   ├── sales_invoices/       planned (post + einvoice status)
│   │   ├── credit_notes/         planned
│   │   ├── purchase_orders/      planned
│   │   ├── purchase_invoices/    planned
│   │   ├── debit_notes/          planned
│   │   └── einvoicing/           planned status helpers; adapters are NOT here
│   ├── inventory_management/     units/ categories/ products/ price_lists/ warehouses/
│   │                             stock/ stock_transfers/ stock_adjustments/  (planned)
│   ├── crm/                      customers/ contacts/
│   │                             leads/ opportunities/ activities/  (planned)
│   ├── communication_service/    planned
│   ├── notifications_service/    planned
│   │
│   ├── integrations/             storage/ (implemented)
│   │                             einvoicing/  zoho.py tally.py generic_peppol_asp.py  (planned)
│   └── workers/                  planned: emails/ imports/ exports/ reports/ pdf/
│                                 einvoice submit / poll / inbound webhook
│
├── alembic/  (versions/ env.py script.py.mako)
├── tests/    (conftest.py, unit/, integration/, api/ — mirroring app/auth, app/erp, …)
├── docs/     (ARCHITECTURE.md, TECH_STACK.md, drawio; openapi/ generated snapshots)
│
├── .env.example  .gitignore  .dockerignore  Dockerfile  docker-compose.yml
├── alembic.ini   pyproject.toml  README.md  Makefile  cursor-instructions.md
```

## Module structure

Modules sit directly under `app/`. A module owns its slices and exposes one router; nested
modules (such as `erp`) aggregate their sub-module routers the same way.

```text
app/crm/
├── router.py                aggregates the slice routers of this module
├── customers/
│   ├── router.py
│   ├── service.py
│   ├── repository.py
│   ├── schemas.py
│   ├── models.py
│   └── dependencies.py
└── contacts/
    └── (same six files)
```

```text
app/erp/
├── router.py                aggregates quotation, suppliers, sales, purchase_invoices, ...
├── quotation/
│   ├── router.py service.py repository.py schemas.py models.py dependencies.py
├── suppliers/
│   └── router.py service.py schemas.py dependencies.py
└── sales_invoices/          planned — post() commits ledger; never calls an ASP SDK
```

Everything a slice needs lives in the slice: its router, business logic, queries, request and
response schemas, ORM models and FastAPI dependencies. Keep each slice self-contained.

## What belongs in `common/` versus a module

`common/` holds things that more than one module genuinely needs: the base repository, the
response envelope and pagination schemas, auth/tenant/permission dependencies, shared utilities,
attachments, and genuinely cross-cutting models (`audit_log`). Identity tables live in
`app/auth/`.

`common/` must never contain module business logic. If something in `common/` only makes sense
for one module, it belongs in that module. If two modules need each other's logic, call the
owning module's service — do not promote that logic into `common/`.

## Router registration

Modules are a code-organisation concept only. They do not appear in the URL — the API surface
is a flat set of resources under `/api/v1`.

The slice router owns its resource prefix and tag. The module router only aggregates, and the
version prefix is applied once in `app/router.py`:

```python
# app/crm/customers/router.py
router = APIRouter(prefix="/customers", tags=["CRM"])

# app/crm/router.py
router = APIRouter()
router.include_router(customers.router)
router.include_router(contacts.router)

# app/router.py
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(erp.router)
api_router.include_router(crm.router)
```

Slice routers never hardcode `/api/v1`. Directories use `snake_case` because Python packages
cannot contain hyphens; the URL path uses hyphenated plural nouns:

```text
app/crm/customers/                   →  /api/v1/customers
app/erp/purchase_invoices/           →  /api/v1/purchase-invoices
app/inventory_management/products/   →  /api/v1/products
app/auth/                            →  /api/v1/users  /api/v1/roles  /api/v1/auth/login
```

Because the URL space is flat, resource segments must be unique across every module. Where two
modules own a similar concept, name the resource for what it actually is rather than
prefixing it with the module: `/customer-payments` and `/supplier-payments`, not
`/sales/payments` and `/purchasing/payments`.

## Model bases

New tables inherit an abstract base from `app/db/base.py` instead of repeating mixins:

```python
from app.db.base import SoftDeleteTenantModel, TenantModel
from app.db.mixins import AuditUserMixin, IsActiveMixin

# Default for masters and documents
class Customer(AuditUserMixin, IsActiveMixin, SoftDeleteTenantModel):
    __tablename__ = "customers"
    ...

# Child / line / identity rows that must not soft-delete
class QuotationLine(TenantModel):
    __tablename__ = "quotation_lines"
    ...
```

Default to `SoftDeleteTenantModel`. Use `TenantModel` only when the row must not have
`deleted_at` (join tables, document lines, login identity). Use `TimestampedModel` only for
rows that are not tenant-scoped (`Tenant`). Extra mixins stay before the abstract base so they
sit above `DeclarativeBase` in the MRO.

## Model registration

Slice models must be imported by `app/db/base.py`, otherwise Alembic autogenerate will not see
them and will silently produce an empty or destructive migration.

## Request flow

```text
Client → Module Router → Authentication → Tenant Resolution → Permission Check
      → Pydantic Validation → Service Layer → Repository Layer → SQLAlchemy → PostgreSQL
```

The router must NOT contain business logic.

## Router rules

Routers are responsible only for HTTP methods, path/query parameters, request and response
schemas, dependency injection, auth dependencies, calling services, and HTTP response handling.

Do not do this:

```python
@router.post("/orders")
async def create_order(data: OrderCreate, db: Session):
    # Business logic does not belong here
    stock = db.query(Stock).filter(...).first()
    if stock.quantity < data.quantity:
        raise HTTPException(...)
    stock.quantity -= data.quantity
    db.commit()
```

Do this instead:

```python
@router.post("/orders")
async def create_order(
    data: OrderCreate,
    service: OrderService = Depends(get_order_service),
):
    return await service.create_order(data)
```

Posting is a named route, not a PATCH:

```python
@router.post("/{invoice_id}/post")
async def post_invoice(...):
    return await service.post(invoice_id)
```

## Service layer rules

Services own business rules, transaction orchestration, validation beyond schema validation,
calls into repositories and integrations, event publishing, and workflow management.
They compute `available_actions` for document responses.

```python
class OrderService:
    async def create_order(self, tenant_id: UUID, data: OrderCreate):
        # Reject if document_date <= tenant lock_date / hard_lock_date
        # Keep the order DRAFT — do not move stock or post ledgers on save
        ...

    async def post(self, tenant_id: UUID, invoice_id: UUID):
        # If-Match / version; Idempotency-Key
        # Inventory service checks allow_negative_stock under SELECT FOR UPDATE
        # If false and qty unavailable → INVENTORY_INSUFFICIENT_STOCK
        # Post AR / tax / GL in the same transaction as the stock movement
        # After commit: outbox EinvoiceSubmitRequested (never call ASP here)
        ...
```

## Repository layer rules

Repositories own database access only: SELECT/INSERT/UPDATE/DELETE, filtering, pagination,
sorting and database-specific queries. They extend the base repository in
`common/repositories/base.py`.

Repositories must not contain business decisions.

```python
# Bad — business rule inside a repository
if customer.is_vip:
    discount = 20

# Good
customer = await repository.get_by_id(customer_id)
```

Stock movements lock the row: `SELECT … FOR UPDATE` on the on-hand record inside the posting
transaction.

## Pydantic schema rules

Never expose SQLAlchemy models directly through API responses.

```text
Request → Pydantic Schema → Service → SQLAlchemy Model
SQLAlchemy Model → Service → Pydantic Response Schema → API
```

Keep the schema variants separate inside the slice's `schemas.py`:

```text
ProductCreate  ProductUpdate  ProductResponse  ProductListResponse  ProductFilter
```

Workflow document responses include `available_actions`, `is_posted`, `version`, money fields,
and e-invoice status when applicable.

## Transaction management

Transactions are controlled at the service / use-case level, not inside repositories.

```text
Post Sales Invoice
      ├── Lock stock rows (SELECT FOR UPDATE)
      ├── Move stock
      ├── Post AR / tax / GL
      ├── Write audit log
      ├── Commit
      └── Outbox: PDF, notification, EinvoiceSubmitRequested
```

Either all ledger operations succeed or the whole transaction rolls back. Do not call
`db.commit()` inside repositories. Side effects after commit are not a substitute for that
transaction.

## Dependency direction

```text
Module Router → Service → Repository → Model → Database
```

Modules may depend on `common/` and on another module's **service**. Never allow
`Models → Services`, `Models → Router`, `Repositories → Router`, a module reaching into another
module's models or repositories, or circular imports between modules. Never import an ASP SDK
from `erp/sales_invoices/service.py`.

## Naming conventions

| Thing            | Convention        | Examples                                                    |
| ---------------- | ----------------- | ----------------------------------------------------------- |
| Packages/modules | `snake_case`      | `auth`, `purchase_invoices`, `crm/customers`                |
| Python files     | `snake_case`      | `service.py`, `repository.py`, `order_workflow_service.py`  |
| Classes          | `PascalCase`      | `LeadService`, `SalesOrderRepository`, `QuotationResponse`  |
| Database tables  | `snake_case`      | `sales_orders`, `sales_order_items`, `purchase_invoices`    |
| API paths        | hyphenated plural | `/customers`, `/products`, `/sales-orders`, `/purchase-invoices` |
| Permissions      | `module.resource.action` | `identity.user.read`, `erp.quotation.approve`, `inventory.stock.adjust`, `erp.einvoice.submit` |

Avoid verb-style routes such as `/getCustomers` or `/createCustomer`.

## Build order

When building the system from scratch, follow this order so dependencies exist before the
modules that need them:

```text
1. Project foundation (core, db, common)
2. Configuration
3. Tenant management
4. Identity — app/auth/ (auth, users, roles, org)
5. Audit logging
6. CRM masters (customers, contacts)
7. Inventory masters (units, categories, products, warehouses)
8. ERP masters then quotations
9. Sales and purchase documents (SO, DN, INV, PO, GRN, bills, payments, credit/debit notes)
10. Accounting (chart of accounts, journals, AR, AP)
11. E-invoicing ASP adapter (after posted sales invoices and credit notes)
12. communication_service, notifications_service, workers, reports, AI
```

## Definition of done for a new slice

- Slice contains its own router, service, repository, schemas, models and dependencies.
- Router is thin, service holds the logic, repository holds the queries.
- Slice router registered on the module router; module router registered on `app/router.py`.
- Models imported by `app/db/base.py`.
- No ORM model leaks through the API.
- Every query is tenant scoped and every endpoint has an explicit permission.
- Pagination, filtering and sorting allowlists are in place on list endpoints.
- Workflow documents return `available_actions`, `is_posted`, `version`, and money fields.
- Errors go through centralized handlers with application error codes.
- Audit logging is emitted for state changes.
- Alembic migration created if the schema changed.
- OpenAPI snapshot updated under `docs/openapi/` if the public contract changed.
- Unfinished modules are feature-flagged off the OpenAPI surface.
- Unit, integration and tenant-isolation tests added under the mirrored `tests/` path
  (`tests/unit/auth/`, not `tests/unit/users_management/`).
