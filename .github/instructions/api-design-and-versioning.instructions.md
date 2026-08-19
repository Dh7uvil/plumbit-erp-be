---
description: API versioning, router mounting, response envelope, error handling, pagination, filtering, sorting and OpenAPI documentation rules.
applyTo: "app/router.py,app/**/router.py,app/**/schemas.py,app/common/schemas/**"
---

# API Design and Versioning

## Versioning

Routers live inside their slice, but the version prefix is applied in exactly one place —
`app/router.py`. A slice router never hardcodes `/api/v1`.

```python
# app/router.py
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(users_management.router)
api_router.include_router(erp.router)
api_router.include_router(crm.router)
```

Module names never appear in the URL. The resulting surface is a flat set of resources:

```text
/api/v1/auth/login
/api/v1/leads
/api/v1/products
/api/v1/quotations
/api/v1/purchase-invoices
```

Breaking changes go into `/api/v2/` by mounting the affected module routers under a second
prefix. Never change the meaning of an existing `v1` field or status code in place. Maintain
backward compatibility unless a breaking change is explicitly requested.

## Resource naming

Directories are `snake_case`; URL segments are hyphenated plural nouns:

```text
app/crm/leads/                       →  /api/v1/leads
app/erp/purchase_invoices/           →  /api/v1/purchase-invoices
app/inventory_management/products/   →  /api/v1/products
```

The URL space is flat, so resource segments must be unique across every module. When two
modules own a similar concept, name the resource for what it is rather than reintroducing the
module as a path segment: `/customer-payments` and `/supplier-payments`.

Avoid verb-style routes such as `/getCustomers` or `/createCustomer`. The HTTP method is
the verb.

## Response envelope

Every response uses the same shape, built from the shared schema in
`app/common/schemas/response.py`.

```json
{
  "success": true,
  "data": {},
  "message": "Customer created successfully",
  "meta": {}
}
```

List responses carry pagination in `meta`:

```json
{
  "success": true,
  "data": [],
  "meta": {
    "page": 1,
    "page_size": 25,
    "total": 250,
    "total_pages": 10
  }
}
```

## Error handling

Never expose raw exceptions to clients.

```python
# Bad
except Exception as e:
    return {"error": str(e)}
```

Use centralized exception handling registered in `app/core/error_handlers.py`, with
application exceptions defined in `app/core/exceptions.py`.

```json
{
  "success": false,
  "error": {
    "code": "INVENTORY_INSUFFICIENT_STOCK",
    "message": "Insufficient stock available",
    "details": {}
  }
}
```

Use stable application-specific error codes rather than relying on HTTP status alone:

```text
AUTH_INVALID_CREDENTIALS   PERMISSION_DENIED     INSUFFICIENT_STOCK
AUTH_TOKEN_EXPIRED         RESOURCE_NOT_FOUND    INVALID_STATUS_TRANSITION
TENANT_ACCESS_DENIED       VALIDATION_ERROR      FINANCIAL_TRANSACTION_LOCKED
DUPLICATE_RESOURCE         INTEGRATION_ERROR
```

Error messages must not leak internal details such as SQL, stack traces, file paths or
another tenant's data.

## Pagination

Every potentially large list endpoint must paginate. There are no unbounded list queries. Use
the shared pagination schema and dependency from `app/common/`.

```text
GET /api/v1/customers?page=1&page_size=25
```

```python
MAX_PAGE_SIZE = 100
```

Reject or clamp `page_size` above the maximum. Never return thousands of records by default.

## Filtering

List endpoints support structured filtering through the slice's `FilterSchema`:

```text
GET /api/v1/customers?search=john&status=active&country=UAE
    &created_from=2026-01-01&created_to=2026-08-01
```

Never build raw SQL from request parameters. Always use parameterized SQLAlchemy queries.

## Sorting

Sorting is controlled and allowlisted:

```text
?sort_by=created_at&sort_order=desc
```

```python
ALLOWED_SORT_FIELDS = {
    "created_at",
    "updated_at",
    "name",
}
```

Never accept arbitrary SQL expressions or column names from users.

## Endpoint checklist

Before an endpoint is considered complete, verify all of:

```text
Authentication        Pagination        Error handling
Authorization         Filtering         Audit logging
Tenant isolation      Sorting           Testing
Validation
```

## OpenAPI documentation

FastAPI's generated documentation is part of the deliverable. Every endpoint declares:

```text
summary        response schema              permission requirements
description    status codes
request schema authentication requirements
```

Tags are where the module structure surfaces to API consumers, since the URL no longer carries
it. Declare the tag on the slice router so the whole module groups together in the docs:

```text
Users Management  ERP  Inventory Management  CRM
Communication Service  Notifications Service
```

Use a slice-level sub-tag only when a module's surface is large enough that a single tag is
unhelpful (for example `ERP / Quotation`, `ERP / Purchase Invoices`).

## Health endpoints

```text
GET /health
GET /health/live
GET /health/ready
```

Readiness verifies required dependencies (database, Redis, required external infrastructure).
Health endpoints must not expose sensitive diagnostic information.
