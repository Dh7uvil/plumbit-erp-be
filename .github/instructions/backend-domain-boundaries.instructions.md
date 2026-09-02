---
description: Boundaries that must not be crossed — tenant isolation, authorization, module ownership, integrations, and financial/workflow domain invariants.
applyTo: "app/**"
---

# Backend Domain Boundaries

This system is a well-structured modular monolith. The boundaries below are what make it
possible to extract a module later, and what keeps tenant and financial data safe. Convenience
never outranks them.

## Architecture principles

Modular architecture with domain-driven module separation, multi-tenant by design, API-first,
PostgreSQL + SQLAlchemy 2.x + Alembic + Pydantic v2, dependency injection through FastAPI,
a service layer for business logic and a repository layer for database access, RBAC plus
permission-based authorization, strict tenant isolation, audit logging, centralized error
handling, async-first where appropriate, background jobs for long-running work, automated
testing, secure-by-default configuration, and structured logging.

---

## 1. The tenant boundary

Single database, multi-tenant. Every tenant-owned table carries `tenant_id`:

```python
class Customer(Base):
    __tablename__ = "customers"

    id = mapped_column(UUID, primary_key=True)
    tenant_id = mapped_column(
        UUID,
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
    )
```

Every tenant-owned query MUST be scoped by `tenant_id`.

```python
# Bad
await db.execute(
    select(Customer).where(Customer.id == customer_id)
)

# Good
await db.execute(
    select(Customer).where(
        Customer.id == customer_id,
        Customer.tenant_id == tenant_id,
    )
)
```

Never trust a `tenant_id` supplied by the frontend, in a body, a query parameter or a header.
The backend derives the tenant from the authenticated user's context.

```text
Authenticated User → Tenant Context → tenant_id
```

Request context carries `current_user`, `current_tenant` and `current_permissions`. Every
repository operation on tenant-owned data receives the tenant context through the shared
dependency in `app/common/dependencies/tenant.py` rather than reconstructing it ad hoc in a
module.

## 2. The authorization boundary

Use RBAC combined with permission-based authorization. Permissions are formatted as
`<module>.<resource>.<action>`, where `<module>` is the owning top-level module:

```text
crm.lead.read           inventory.stock.read     erp.quotation.approve
crm.customer.create     inventory.stock.adjust   erp.sales_order.create
crm.customer.update     inventory.product.read   erp.purchase_invoice.approve
crm.customer.delete     users.role.assign        erp.journal_entry.post
```

A role such as `Sales Manager` is a bundle of those permissions. Authorization is enforced at
the API/service boundary using the shared permission dependency in `app/common/dependencies/` —
never rely on frontend permissions for security.

## 3. The authentication boundary

Authentication is centralized.

```text
Login → Validate Credentials → Access Token → Refresh Token
Authenticated Request → Validate Token → Load User → Load Tenant
                     → Check Account Status → Check Permissions
```

Never store plain-text passwords, return passwords through APIs, trust user IDs from request
bodies, trust tenant IDs from frontend headers without verification, or keep JWT secrets in
source code.

## 4. Module ownership

Each top-level module owns its business rules, its routers, its models and its tables.

```text
users_management        Auth, Users, Roles, Permissions, Tenants
erp                     Quotation, Sales Orders, Purchase Invoices, Purchase Orders,
                        Accounting (Accounts, Journals, Receivables, Payables, Taxes),
                        Logistics (Imports, Exports, Shipments, Containers),
                        Exchange Rates (daily user-entered rates), Suppliers
inventory_management    Products, Categories, Warehouses, Stock, Transfers, Adjustments
crm                     Leads, Customers, Contacts, Opportunities, Activities
communication_service   Email, WhatsApp, Chat, Meetings
notifications_service   In-App, Email, WhatsApp and Push notifications, templates, delivery status
```

A module never reaches into another module's models, repositories or tables. It calls the
owning module's **service**:

```text
Bad:   CRM Service → Inventory SQLAlchemy Model
Good:  CRM Service → Inventory Service
```

Shared code goes in `app/common/` only when more than one module genuinely needs it, and
`app/common/` never holds module business logic. Two modules needing the same rule is a signal
that one of them owns it and the other should call it.

## 5. Cross-module workflows

When a workflow spans modules, coordinate it with an orchestration service instead of
coupling the modules to each other.

```text
erp/sales → inventory_management → erp/accounting → notifications_service
```

For example, `OrderWorkflowService` inside `erp/sales/` calls each module's service and owns
the transaction boundary for the workflow. The orchestrator lives in the module that owns the
business process, not in `app/common/`.

## 6. Events

For loosely coupled side effects, publish domain/application events.

```text
SalesOrderCreated
        ├── Update Inventory
        ├── Create Notification
        ├── Send Email
        └── Update Analytics
```

Events fit notifications, audit logging, analytics, AI processing, integrations and background
jobs. They are not a substitute for a transaction when the operations must be atomic.

## 7. Third-party integrations

All third-party integrations live under `app/integrations/`:

```text
integrations/
├── whatsapp/   self-hosted Go server
├── email/      Amazon SES
├── video/      Agora
├── storage/    S3 / MinIO
├── ai/         OpenAI GPT-5.4 Mini
└── forecast/   Prophet · XGBoost · LightGBM · Statsmodels
```

An integration exists only when the capability genuinely comes from outside. Exchange rates,
for example, are not an integration — see the currency rule below.

Never call a third-party SDK directly from a business module. Use provider abstractions so a
provider can be swapped without rewriting business logic:

```text
NotificationService → WhatsAppProvider → self-hosted Go server
```

## 8. Notifications and communication

`notifications_service` is the only module that decides how a user is notified. It fans out to
In-App, Email, WhatsApp and Push, and records delivery status
(`pending`, `queued`, `sent`, `delivered`, `failed`, `read`). `communication_service` owns
user-to-user communication — email threads, WhatsApp conversations, chat and meetings
(Agora for video).

Business modules never talk to a provider directly:

```text
Bad:   erp/sales/service.py → Twilio API
Good:  erp/sales/service.py → notifications_service → WhatsApp Go adapter
```

## 9. Background work

Long-running operations must run in background workers, never inside an HTTP request:
email and WhatsApp sending, Excel imports and exports, large reports, AI forecasting,
notifications, file processing, scheduled tasks and inventory forecasting.

Imports and exports follow the job pattern:

```text
API → Create Job → Queue → Background Worker → Process File → Store Result → Notify User
```

Supported formats are CSV, XLSX and JSON. Validate imported data before any database write and
use staging tables for large imports.

## 10. Financial invariants (immutability)

An ERP is not a CRUD app. Overwriting a posted row is a fatal design error.

Once a financial transaction is `POSTED` it is not directly editable or deletable. If an
invoice for AED 1,000 was posted in July, a user must not change that cell to AED 800 in
August. Corrections happen only through a **new** document in the **open** period: reversal,
credit note, debit note or adjustment voucher. That preserves the double-entry audit trail
accountants and tax authorities require.

Deleting a posted journal entry is never allowed.

Do not use floating-point numbers for money. Use `Decimal` in Python and `NUMERIC`/`DECIMAL`
in PostgreSQL. Every financial transaction preserves `currency`, `exchange_rate`,
`base_currency`, `base_amount` and `foreign_amount`.

Exchange rates are entered by the user, not fetched from a provider. The `erp/exchange_rates`
slice exposes an API where a user records the rate for a currency pair on a given day, stored
uniquely per `(tenant_id, from_currency, to_currency, effective_date)`. Every transaction on
that day converts using that day's rate.

The rate in force is resolved once, at the moment the transaction is created, and the resulting
`exchange_rate` is stored on the transaction row. Never recompute a historical document's base
amount from a later rate, and never fall back to an arbitrary rate when the day's rate is
missing — reject the operation instead.

## 11. Negative stock (inventory rule)

Treat on-hand quantity as a guarded invariant, not a number field you decrement blindly.

Each tenant has `allow_negative_stock` (default **false**). When it is false, validating a
delivery note, sales dispatch or stock-out **must** abort if available physical stock is less
than the requested quantity:

```text
Error: Insufficient physical stock. Post the purchase invoice / GRN first.
```

The check belongs in the inventory **service**, inside the same database transaction as the
movement, with a row lock so concurrent sales cannot both pass. Do not rely on the UI.

When the toggle is true (warehouse-speed mode), negative on-hand is allowed but must still be
visible on the warehouse and must **block period close**.

## 12. Period lock (monthly close)

Do not freeze the whole application with a manual "end of month" tool. Store per tenant:

```text
lock_date         blocks non-adviser roles from mutating dated vouchers
hard_lock_date    blocks every role, including advisers
```

On create, update or delete of sales, purchase, invoice, bill, stock movement or journal
entry, compare `document_date` to the lock:

```text
if document_date <= applicable_lock_date  →  reject
"This period is closed for auditing."
```

Setting or advancing a lock date is refused while **any warehouse** for that tenant has
negative on-hand. Clear inventory errors first. Locking and unlocking are audited. AI may
**flag** unposted GRNs and anomalies before close; it must not set the lock.

## 13. Invoice posting (ledger rule)

Every sales invoice, purchase invoice and journal starts as `DRAFT`. Drafts are data only:
no inventory movement, no accounts receivable/payable, no tax, no general ledger.

Posting is an explicit action (`Confirm` / `Post`, optionally a permissioned batch of
audited drafts). On post, in one transaction:

```text
DRAFT → POSTED
  ├── inventory service (if goods) — respects allow_negative_stock
  ├── AR / AP and tax ledgers
  └── audit log
```

`Sent` / `Approved` in the product UI maps to `POSTED` on the API. Never post as a side
effect of "save".

## 14. Workflow status invariants

Status transitions are implemented in services and validated against an explicit state machine.

```text
Draft → Submitted → Approved → Confirmed → Completed
```

`Completed → Draft` is invalid unless a reversal/reopen workflow is explicitly implemented.
Never allow arbitrary status changes from client input.

## 15. Document numbers

ERP documents carry human-readable numbers:

```text
QUO-2026-000001  SO-2026-000001  PO-2026-000001  INV-2026-000001  GRN-2026-000001
```

Do not generate these with application-level counters alone. Use a database-safe mechanism
(sequence or locked counter row) so concurrent requests cannot produce duplicates.

## 16. AI boundary

AI never directly modifies critical ERP data.

```text
AI Forecast / alert → Recommendation → User Review → Approval → ERP Action
```

AI may recommend reorder quantities, expected demand, stock shortages, shipment projections
and sales forecasts. It may also:

- Warn that physical stock is missing but a PO/GRN is due (lead time from history) and offer
  to **reserve** only after the user confirms.
- Run a pre-close scan and **flag** unposted purchase invoices where goods were already
  received, so accounting can fix them before lock.

It must not silently create purchase orders, change accounting entries, change stock, approve
payments, set lock dates or delete records.

Do not send sensitive ERP data to external AI providers unless explicitly permitted. Keep AI
behind `app/integrations/ai/` (OpenAI GPT-5.4 Mini) and forecast workers
(`Prophet` / `XGBoost` / `LightGBM` / `Statsmodels`) so providers can change.

## 17. Dependency direction

```text
Module Router → Service → Repository → Model → Database
```

Allowed: any module may depend on `app/common/` and on another module's **service**.

Forbidden: `Models → Services`, `Models → Router`, `Repositories → Router`, one module
importing another module's models or repositories, module business logic living in
`app/common/`, and circular imports between modules.
