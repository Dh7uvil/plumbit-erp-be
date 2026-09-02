---
description: API versioning, router mounting, response envelope, error handling, pagination, filtering, sorting, document contract and OpenAPI documentation rules.
applyTo: "app/router.py,app/**/router.py,app/**/schemas.py,app/common/schemas/**"
---

# API Design and Versioning

## Versioning

Routers live inside their slice, but the version prefix is applied in exactly one place —
`app/router.py`. A slice router never hardcodes `/api/v1`. Identity is `app.auth.router`, not
`users_management`.

```python
# app/router.py
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(erp.router)
api_router.include_router(crm.router)
api_router.include_router(inventory_management.router)
```

Module names never appear in the URL. The resulting surface is a flat set of resources:

```text
/api/v1/auth/login
/api/v1/customers
/api/v1/products
/api/v1/quotations
/api/v1/purchase-invoices
/api/v1/credit-notes
/api/v1/debit-notes
/api/v1/customer-payments
/api/v1/supplier-payments
```

Breaking changes go into `/api/v2/` by mounting the affected module routers under a second
prefix. Never change the meaning of an existing `v1` field or status code in place. Maintain
backward compatibility unless a breaking change is explicitly requested.

Feature-flag unfinished modules so they do not appear in OpenAPI as empty stubs.

## Resource naming

Directories are `snake_case`; URL segments are hyphenated plural nouns:

```text
app/crm/leads/                       →  /api/v1/leads
app/erp/purchase_invoices/           →  /api/v1/purchase-invoices
app/inventory_management/products/   →  /api/v1/products
app/auth/                            →  /api/v1/auth, /users, /roles, /tenants, …
```

The URL space is flat, so resource segments must be unique across every module. When two
modules own a similar concept, name the resource for what it is rather than reintroducing the
module as a path segment: `/customer-payments` and `/supplier-payments`, `/credit-notes` and
`/debit-notes`, `/delivery-notes`.

Avoid verb-style routes such as `/getCustomers` or `/createCustomer`. The HTTP method is
the verb. Workflow verbs that are not CRUD belong as sub-resources on the document:

```text
POST /api/v1/sales-invoices/{id}/post
POST /api/v1/sales-invoices/{id}/confirm
POST /api/v1/sales-invoices/{id}/einvoice/submit
POST /api/v1/credit-notes
POST /api/v1/debit-notes
```

Posting is never a side effect of PATCH. Corrections are new documents that reference the
posted original — never PATCH of posted amounts.

## Document-response contract

Every workflow document (quotation, order, invoice, credit/debit note, payment, GRN, delivery
note, journal) returns at least:

```text
status              available_actions[]     document_number
currency            exchange_rate           base_amount / foreign_amount
is_posted           document_date           version
```

When e-invoicing applies (sales invoices and credit notes), also return:

```text
einvoice_status     einvoice_uuid     exchanged_at
asp_provider        asp_error_code    asp_error_message
```

`available_actions` is computed by the service for the current user and document. It is the
**only** legal source of UI buttons. Never let the client invent a transition table. Gate each
action on permission server-side even if the string is present.

`available_actions` may include `submit_einvoice` only when the document is `POSTED`, PINT-AE
data is complete, and the tenant has an ASP configured. Drafts never include it.

List filters for in-scope documents include `einvoice_status`.

## Idempotency and concurrency

- `Idempotency-Key` is **required** on post, payment, stock-movement, and e-invoice submit
  writes. Replays with the same key return the original result. A conflicting body with the
  same key is `IDEMPOTENCY_CONFLICT`.
- `If-Match` (or body `version`) is required on document PATCH and post. A stale version is
  `409 CONFLICT` with `DOCUMENT_STALE`.
- E-invoice submit is idempotent on document id + version. A second submit after `exchanged`
  is `EINVOICE_ALREADY_EXCHANGED`.

## E-invoicing routes

Status and submit live on the ERP document. Provider webhooks are not a public business route.

```text
POST /api/v1/sales-invoices/{id}/einvoice/submit     erp.einvoice.submit
GET  /api/v1/sales-invoices?einvoice_status=pending  erp.einvoice.read (or document read)
POST /api/v1/integrations/einvoicing/webhooks/{provider}
```

The webhook verifies the ASP signature inside `app/integrations/einvoicing/`, then the ERP
service creates a **DRAFT** purchase invoice. Never auto-post inbound e-bills. Rate-limit
post, payment and e-invoice submit per tenant.

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
    "message": "Insufficient physical stock. Post the purchase invoice / GRN first.",
    "details": {
      "warehouse_id": "…",
      "warehouse_code": "MAIN",
      "available_qty": "3.000",
      "requested_qty": "10.000"
    }
  }
}
```

Use stable application-specific error codes rather than relying on HTTP status alone:

```text
AUTH_INVALID_CREDENTIALS              PERMISSION_DENIED
AUTH_TOKEN_EXPIRED                    RESOURCE_NOT_FOUND
TENANT_ACCESS_DENIED                  VALIDATION_ERROR
DUPLICATE_RESOURCE                    INVALID_STATUS_TRANSITION
INTEGRATION_ERROR                     FINANCIAL_TRANSACTION_LOCKED
INVENTORY_INSUFFICIENT_STOCK          PERIOD_LOCKED
PERIOD_LOCK_BLOCKED_NEGATIVE_STOCK    DRAFT_DOCUMENT_NOT_POSTED
DOCUMENT_STALE                        IDEMPOTENCY_CONFLICT
EXCHANGE_RATE_MISSING                 EINVOICE_NOT_READY
EINVOICE_REJECTED                     EINVOICE_ASP_UNAVAILABLE
EINVOICE_ALREADY_EXCHANGED
```

`INSUFFICIENT_STOCK` exists in current code; new inventory/posting work must emit
`INVENTORY_INSUFFICIENT_STOCK` (keep a compatibility alias if needed).

Error `details` for stock and lock include warehouse, available qty, and lock date so the UI
can explain the block. E-invoice errors include `asp_error_code` / `asp_error_message` without
leaking provider credentials.

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
GET /api/v1/sales-invoices?einvoice_status=pending&is_posted=true
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
Validation            available_actions (workflow documents)
Idempotency-Key / If-Match where required
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
Identity  ERP  Inventory Management  CRM
Communication Service  Notifications Service
```

Use a slice-level sub-tag only when a module's surface is large enough that a single tag is
unhelpful (for example `ERP / Quotation`, `ERP / Purchase Invoices`).

Commit an updated snapshot under `docs/openapi/` whenever the public contract changes.

## Health endpoints

```text
GET /health
GET /health/live
GET /health/ready
```

Readiness verifies required dependencies (PostgreSQL today). Do not require Redis. Health
endpoints must not expose sensitive diagnostic information.
