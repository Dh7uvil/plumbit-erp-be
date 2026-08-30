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
   existing module.
3. Identify existing services, repositories, schemas and common utilities and reuse them.
4. Identify related models and database relationships.
5. Identify the permissions the feature needs.
6. Identify tenant isolation requirements.
7. Identify audit and transaction requirements.
8. Avoid duplicate functionality and unnecessary dependencies.
9. Implement the smallest clean solution.

## Top-level modules

These are the only top-level modules. Everything belongs to exactly one of them.

| Module                   | Owns                                                                     |
| ------------------------ | ------------------------------------------------------------------------ |
| `users_management`       | auth, users, roles, permissions, tenants                                  |
| `erp`                    | quotation, sales, purchase_invoices, purchase_orders, accounting, logistics, exchange_rates, suppliers |
| `inventory_management`   | products, categories, warehouses, stock, transfers, adjustments           |
| `crm`                    | leads, customers, contacts, opportunities, activities                     |
| `communication_service`  | email, whatsapp, chat, meetings                                           |
| `notifications_service`  | notifications, templates, delivery status                                 |

Adding a new top-level module requires explicit justification. If a feature is close to an
existing module's domain, it becomes a slice inside that module instead.

## Repository layout

```text
erp-backend/
│
├── app/
│   ├── main.py
│   ├── router.py                 mounts every module router under /api/v1
│   │
│   ├── core/                     config.py security.py permissions.py exceptions.py
│   │                             error_handlers.py middleware.py logging.py constants.py enums.py
│   ├── db/                       base.py session.py mixins.py seed.py
│   │
│   ├── common/                   shared building blocks — no module business logic
│   │   ├── models/               tenant.py user.py role.py permission.py audit_log.py
│   │   ├── schemas/              response.py pagination.py filters.py auth.py
│   │   ├── repositories/         base.py
│   │   ├── services/             audit.py
│   │   ├── dependencies/         auth.py tenant.py permissions.py pagination.py
│   │   └── utils/                datetime.py currency.py validators.py generators.py files.py
│   │
│   ├── users_management/         auth/ users/ roles/ permissions/ tenants/
│   ├── erp/
│   │   ├── quotation/
│   │   ├── sales/
│   │   ├── purchase_invoices/
│   │   ├── purchase_orders/
│   │   ├── accounting/
│   │   ├── logistics/
│   │   ├── exchange_rates/
│   │   └── suppliers/
│   ├── inventory_management/     products/ categories/ warehouses/ stock/
│   │                             stock_transfers/ stock_adjustments/
│   ├── crm/                      leads/ customers/ contacts/ opportunities/ activities/
│   ├── communication_service/    email/ whatsapp/ chat/ meetings/
│   ├── notifications_service/    notifications/ templates/ delivery/
│   │
│   ├── integrations/             email/ whatsapp/ payments/ calendar/ video/ storage/
│   └── workers/                  emails/ notifications/ imports/ exports/ reports/ ai/
│
├── alembic/  (versions/ env.py script.py.mako)
├── tests/    (conftest.py, unit/, integration/, api/ — mirroring the module packages)
├── scripts/  (seed_database.py, create_admin.py, health_check.py)
├── docs/     (architecture.md, api.md, database.md, security.md, multi-tenancy.md, integrations.md)
│
├── .env.example  .gitignore  .dockerignore  Dockerfile  docker-compose.yml
├── alembic.ini   pyproject.toml  README.md  Makefile
```

## Module structure

Modules sit directly under `app/`. A module owns its slices and exposes one router; nested
modules (such as `erp`) aggregate their sub-module routers the same way.

```text
app/crm/
├── router.py                aggregates the slice routers of this module
├── leads/
│   ├── router.py
│   ├── service.py
│   ├── repository.py
│   ├── schemas.py
│   ├── models.py
│   └── dependencies.py
├── customers/
│   └── (same six files)
└── opportunities/
    └── (same six files)
```

```text
app/erp/
├── router.py                aggregates quotation, suppliers, sales, purchase_invoices, ...
├── quotation/
│   ├── router.py service.py repository.py schemas.py models.py dependencies.py
├── suppliers/
│   └── router.py service.py schemas.py dependencies.py
├── sales/
│   └── (same six files)
└── purchase_invoices/
    └── (same six files)
```

Everything a slice needs lives in the slice: its router, business logic, queries, request and
response schemas, ORM models and FastAPI dependencies. Keep each slice self-contained.

## What belongs in `common/` versus a module

`common/` holds things that more than one module genuinely needs: the base repository, the
response envelope and pagination schemas, auth/tenant/permission dependencies, shared utilities,
and the cross-cutting models (`tenant`, `user`, `role`, `permission`, `audit_log`).

`common/` must never contain module business logic. If something in `common/` only makes sense
for one module, it belongs in that module. If two modules need each other's logic, call the
owning module's service — do not promote that logic into `common/`.

## Router registration

Modules are a code-organisation concept only. They do not appear in the URL — the API surface
is a flat set of resources under `/api/v1`.

The slice router owns its resource prefix and tag. The module router only aggregates, and the
version prefix is applied once in `app/router.py`:

```python
# app/crm/leads/router.py
router = APIRouter(prefix="/leads", tags=["CRM"])

# app/crm/router.py
router = APIRouter()
router.include_router(leads.router)
router.include_router(customers.router)

# app/router.py
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(users_management.router)
api_router.include_router(erp.router)
api_router.include_router(crm.router)
```

Slice routers never hardcode `/api/v1`. Directories use `snake_case` because Python packages
cannot contain hyphens; the URL path uses hyphenated plural nouns:

```text
app/crm/leads/                       →  /api/v1/leads
app/erp/purchase_invoices/           →  /api/v1/purchase-invoices
app/inventory_management/products/   →  /api/v1/products
app/users_management/users/          →  /api/v1/users
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

## Service layer rules

Services own business rules, transaction orchestration, validation beyond schema validation,
calls into repositories and integrations, event publishing, and workflow management.

```python
class OrderService:
    async def create_order(self, tenant_id: UUID, data: OrderCreate):
        # Validate business rules
        # Validate customer, products, inventory
        # Calculate totals
        # Create order
        # Update inventory
        # Create audit log
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

## Transaction management

Transactions are controlled at the service / use-case level, not inside repositories.

```text
Create Sales Order
      ├── Create Order
      ├── Create Order Items
      ├── Reserve Stock
      ├── Update Inventory
      ├── Create Audit Log
      └── Commit
```

Either all operations succeed or the whole transaction rolls back. Do not call `db.commit()`
inside repositories.

## Dependency direction

```text
Module Router → Service → Repository → Model → Database
```

Modules may depend on `common/` and on another module's **service**. Never allow
`Models → Services`, `Models → Router`, `Repositories → Router`, a module reaching into another
module's models or repositories, or circular imports between modules.

## Naming conventions

| Thing            | Convention        | Examples                                                    |
| ---------------- | ----------------- | ----------------------------------------------------------- |
| Packages/modules | `snake_case`      | `users_management`, `purchase_invoices`, `crm/leads`        |
| Python files     | `snake_case`      | `service.py`, `repository.py`, `order_workflow_service.py`  |
| Classes          | `PascalCase`      | `LeadService`, `SalesOrderRepository`, `QuotationResponse`  |
| Database tables  | `snake_case`      | `sales_orders`, `sales_order_items`, `purchase_invoices`    |
| API paths        | hyphenated plural | `/leads`, `/products`, `/sales-orders`, `/purchase-invoices`|
| Permissions      | `module.resource.action` | `crm.lead.read`, `erp.quotation.approve`, `inventory.stock.adjust` |

Avoid verb-style routes such as `/getCustomers` or `/createCustomer`.

## Build order

When building the system from scratch, follow this order so dependencies exist before the
modules that need them:

```text
1. Project foundation (core, db, common)      6. crm
2. Configuration                              7. inventory_management
3. Tenant management                          8. erp (quotation → sales → purchase_invoices → accounting)
4. users_management (auth, users, roles)      9. communication_service
5. Audit logging                             10. notifications_service, workers, reports, AI
```

## Definition of done for a new slice

- Slice contains its own router, service, repository, schemas, models and dependencies.
- Router is thin, service holds the logic, repository holds the queries.
- Slice router registered on the module router; module router registered on `app/router.py`.
- Models imported by `app/db/base.py`.
- No ORM model leaks through the API.
- Every query is tenant scoped and every endpoint has an explicit permission.
- Pagination, filtering and sorting allowlists are in place on list endpoints.
- Errors go through centralized handlers with application error codes.
- Audit logging is emitted for state changes.
- Alembic migration created if the schema changed.
- Unit, integration and tenant-isolation tests added under the mirrored `tests/` path.
