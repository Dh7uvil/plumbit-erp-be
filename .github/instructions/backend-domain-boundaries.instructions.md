---
description: Boundaries that must not be crossed — tenant isolation, authorization, module ownership, integrations, financial/workflow domain invariants, UAE VAT, and e-invoicing.
applyTo: "app/**"
---

# Backend Domain Boundaries

This system is a well-structured modular monolith. The boundaries below are what make it
possible to extract a module later, and what keeps tenant and financial data safe. Convenience
never outranks them.

Plumbit is a UAE trading ERP (Zoho Books + Inventory + CRM / Odoo Sales, Purchase, Inventory,
Accounting, CRM). Out of scope: manufacturing, POS, full payroll, e-commerce, projects/timesheets,
recurring invoices, banking/PDC. Plumbit will **not** become a Peppol Access Point or MoF-accredited
ASP, and will **not** dual-write the ledger into Zoho Books or TallyPrime.

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

Documents may carry `branch_id` for reporting and default warehouse/address. Tenant still comes
from the session — `branch_id` is never a substitute for `tenant_id`.

## 2. The authorization boundary

Use RBAC combined with permission-based authorization. Permissions are formatted as
`<module>.<resource>.<action>`, where `<module>` is the catalog prefix (`identity`, `crm`,
`inventory`, `erp`) — not the Python package name:

```text
identity.user.read          identity.role.update       identity.organization.update
identity.attachment.read    erp.quotation.approve      erp.period.lock
crm.customer.create         inventory.stock.adjust     erp.sales_order.create
crm.customer.update         inventory.product.read     erp.purchase_invoice.approve
crm.lead.read               inventory.stock.read       erp.journal_entry.post
erp.einvoice.submit         erp.einvoice.read          erp.credit_note.create
```

Do not invent `users.*` codes. The live catalog in `app/auth/catalog.py` is `identity.*` /
`crm.*` / `inventory.*` / `erp.*`.

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
Identity is the Python package `app/auth/` — keep that name.

```text
auth (Identity)         implemented: auth, users, roles, permissions, tenants/org-settings,
                        branches, departments, employees (nested), audit-logs
                        (attachments live in app/common/attachments/ with identity.attachment.*)
                        planned: tenant operational settings (allow_negative_stock, lock dates)

erp                     implemented: currencies, exchange_rates, taxes, payment_terms,
                        terms_templates, document_sequences, suppliers, quotations
                        planned: sales_orders, sales_invoices, credit_notes, customer_payments,
                        purchase_orders, purchase_invoices, debit_notes, supplier_payments,
                        accounting (chart of accounts, journals, AR, AP),
                        logistics (imports, exports, shipments, containers),
                        einvoicing status APIs (on sales invoices and credit notes;
                        inbound e-bills as draft purchase invoices)

inventory_management    implemented: units, categories, products, price_lists, warehouses
                        planned: stock, stock_transfers, stock_adjustments, goods_receipts (GRN),
                        delivery_notes, sales_returns

crm                     implemented: customers, contacts
                        planned: leads, opportunities, activities

communication_service   planned: Email, WhatsApp, Chat, Meetings
notifications_service   planned: In-App, Email, WhatsApp and Push, templates, delivery status
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

For loosely coupled side effects, publish domain/application events **after commit** through a
transactional outbox. Events are not a substitute for the posting transaction.

```text
SalesOrderCreated / InvoicePosted
        ├── Create Notification
        ├── Queue PDF / email
        ├── EinvoiceSubmitRequested   (after POSTED, never from DRAFT)
        └── Update Analytics
```

Events fit notifications, audit logging, analytics, AI processing, integrations, PDF generation
and e-invoice submit/poll. Stock, AR/AP, tax and GL that must succeed together stay in the
posting transaction — they are not fired as after-the-fact events.

## 7. Third-party integrations

All third-party integrations live under `app/integrations/`:

```text
integrations/
├── storage/      S3 / MinIO          (implemented)
├── whatsapp/     self-hosted Go server
├── email/        Amazon SES
├── video/        Agora
├── ai/           OpenAI GPT-5.4 Mini
├── forecast/     Prophet · XGBoost · LightGBM · Statsmodels
└── einvoicing/   MoF-accredited ASP adapters (Zoho, Tally, generic Peppol ASP)
```

An integration exists only when the capability genuinely comes from outside. Exchange rates,
for example, are not an integration — see the currency rule below. UAE e-invoicing **is** an
integration: Plumbit owns the ledger; the ASP owns PINT-AE XML, signing, Peppol and FTA
reporting. See section 18.

Never call a third-party SDK directly from a business module. Use provider abstractions so a
provider can be swapped without rewriting business logic:

```text
NotificationService → WhatsAppProvider → self-hosted Go server
SalesInvoiceService.post() → outbox EinvoiceSubmitRequested
  → worker → EinvoiceProvider.submit(canonical_payload) → ASP
```

Never call an ASP from `erp/sales_invoices/service.py` — only via `app/integrations/einvoicing/`.

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
email and WhatsApp sending, Excel imports and exports, large reports, PDF/print, AI forecasting,
notifications, file processing, scheduled tasks, inventory forecasting, e-invoice submit, poll
and inbound webhook processing.

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
missing — reject the operation with `EXCHANGE_RATE_MISSING` instead.

A document that is e-invoice `exchanged` is as immutable as `POSTED`. Rejection does not unlock
the original row; the user posts a credit note (and a new invoice if needed) in the open period.

## 11. Negative stock (inventory rule)

Treat on-hand quantity as a guarded invariant, not a number field you decrement blindly.

Each tenant has `allow_negative_stock` (default **false**), stored as a first-class tenant
column (not a JSONB extra) when that slice is built. When it is false, validating a
delivery note, sales dispatch or stock-out **must** abort if available physical stock is less
than the requested quantity:

```text
Error code: INVENTORY_INSUFFICIENT_STOCK
Error: Insufficient physical stock. Post the purchase invoice / GRN first.
details: warehouse_id, warehouse_code, available_qty, requested_qty
```

The check belongs in the inventory **service**, inside the same database transaction as the
movement, with `SELECT FOR UPDATE` on the stock row so concurrent sales cannot both pass. Do
not rely on the UI.

When the toggle is true (warehouse-speed mode), negative on-hand is allowed but must still be
visible on the warehouse and must **block period close**.

## 12. Period lock (monthly close)

Do not freeze the whole application with a manual "end of month" tool. Store per tenant as
first-class columns:

```text
lock_date         blocks non-adviser roles from mutating dated vouchers
hard_lock_date    blocks every role, including advisers
```

On create, update or delete of sales, purchase, invoice, bill, stock movement or journal
entry, compare `document_date` to the lock:

```text
if document_date <= applicable_lock_date  →  reject
code: PERIOD_LOCKED
details: lock_date, hard_lock_date, document_date
"This period is closed for auditing."
```

Setting or advancing a lock date is refused while **any warehouse** for that tenant has
negative on-hand (`PERIOD_LOCK_BLOCKED_NEGATIVE_STOCK`, details include warehouse and qty).
Clear inventory errors first. Locking and unlocking are audited. Changing these columns is
permissioned: org profile stays `identity.organization.update`; advancing locks uses dedicated
`erp.period.lock` when that permission exists. AI may **flag** unposted GRNs and anomalies
before close; it must not set the lock.

## 13. Invoice posting (ledger rule)

Every sales invoice, purchase invoice and journal starts as `DRAFT`. Drafts are data only:
no inventory movement, no accounts receivable/payable, no tax, no general ledger.

Posting is an explicit action (`Confirm` / `Post`, optionally a permissioned batch of
audited drafts). Endpoint: `POST /{resource}/{id}/post` (or `/confirm`) — never a side effect
of PATCH. Require `Idempotency-Key` on post, payment and stock-movement writes. Require
`If-Match` / `version` on document PATCH and post; stale writes are `409 DOCUMENT_STALE`.

On post, in one transaction:

```text
DRAFT → POSTED
  ├── inventory service (if goods) — respects allow_negative_stock (SELECT FOR UPDATE)
  ├── AR / AP and tax ledgers
  ├── GL
  └── audit log
```

`Sent` / `Approved` in the product UI maps to `POSTED` on the API for invoices. Never post as
a side effect of "save". A draft that has not been posted must not be treated as a ledger
document (`DRAFT_DOCUMENT_NOT_POSTED`).

Corrections: `POST /credit-notes` / `POST /debit-notes` referencing the posted document — never
PATCH of posted amounts.

After the posting transaction commits, enqueue `EinvoiceSubmitRequested` for in-scope documents
(sales invoices and credit notes). Posting must not wait on the ASP — the ledger stays
available if Peppol is down.

## 14. Workflow status invariants

Status transitions are implemented in services and validated against an explicit state machine.
The service computes `available_actions` for the current user and document; that list is the
only legal source of UI buttons.

```text
Draft → Submitted → Approved → Confirmed → Completed
```

Invoice lifecycle relative to the ledger:

```text
DRAFT  →  POSTED (local ledger)  →  einvoice pending  →  exchanged
                                              ↘ rejected → credit note (+ new invoice)
```

`Completed → Draft` is invalid unless a reversal/reopen workflow is explicitly implemented.
Never allow arbitrary status changes from client input. Never let the client supply
`available_actions`.

## 15. Document numbers

ERP documents carry human-readable numbers:

```text
QUO-2026-000001  SO-2026-000001  DN-2026-000001  INV-2026-000001
CN-2026-000001   PO-2026-000001  GRN-2026-000001 BILL-2026-000001
SDN-2026-000001
```

Prefixes: `QUO`, `SO`, `DN` (delivery notes), `INV`, `CN` (credit notes), `PO`, `GRN`, `BILL`
(purchase invoices), `SDN` (debit notes). URL resources are unique even if a prefix is shared
(`/credit-notes`, `/debit-notes`, `/delivery-notes`, `/customer-payments`, `/supplier-payments`).

Do not generate these with application-level counters alone. Use a database-safe mechanism
(sequence or locked counter row) so concurrent requests cannot produce duplicates. Uniqueness
is `(tenant_id, document_number)` per document type.

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
payments, set lock dates, submit e-invoices or delete records.

Do not send sensitive ERP data to external AI providers unless explicitly permitted. Keep AI
behind `app/integrations/ai/` (OpenAI GPT-5.4 Mini) and forecast workers
(`Prophet` / `XGBoost` / `LightGBM` / `Statsmodels`) so providers can change.

## 17. UAE VAT

VAT lives on parties and documents. Domain code already has TRN, tax treatment, place of
supply (emirates), and `STANDARD` / `ZERO_RATED` / `EXEMPT` / `OUT_OF_SCOPE`. Treat these as
foundation, not display-only extras.

```text
TaxTreatment     REGISTERED | UNREGISTERED | EXPORT | GCC | EXEMPT
TaxCategory      STANDARD | ZERO_RATED | EXEMPT | OUT_OF_SCOPE
PlaceOfSupply    ABU_DHABI | DUBAI | SHARJAH | AJMAN | UMM_AL_QUWAIN |
                 RAS_AL_KHAIMAH | FUJAIRAH | OUTSIDE_UAE
```

Rules:

- Require `trn` when `tax_treatment` is `REGISTERED`.
- Derive place of supply from the relevant address emirate (shipping, then billing).
- Resolve tax category from treatment + place of supply + line item category in the **service**,
  never in the client.
- Store tax amounts on the document at post time. Never recompute posted tax from a later rate,
  a later customer treatment, or a later tax master.
- PINT-AE needs more than this VAT layer (Peppol IDs, UQC, allowance/charge reason codes). See
  section 18 — current TRN / place of supply / tax category are necessary but not sufficient
  for `submit_einvoice` to appear in `available_actions`.

## 18. UAE e-invoicing

UAE e-invoicing is a Peppol **five-corner** model under MoF Ministerial Decision 64 of 2025.
Mandates are phased (large taxpayers from Jan 2027; remaining VAT-registered from Jul 2027).
Treat e-invoicing as a foundation, not an afterthought.

```text
Plumbit          Corner 1 / 5   seller or buyer ERP — system of record
MoF ASP          Corner 2 / 4   validates, signs, transmits (Zoho, Tally, ClearTax, Pagero, …)
Peppol           Corner 3
FTA              receives a Tax Data Document via the ASP (reporting window commonly 14 days)
```

Documents in scope first: **sales invoices and credit notes** (PINT-AE Electronic Invoices and
Electronic Credit Notes). Inbound e-bills (draft purchase invoices) second. Debit notes,
payments and POS are ASP-side extras — do not invent them in Plumbit until the invoice path
exists.

### What Plumbit owns vs what the ASP owns

| Plumbit (ERP) | ASP |
| --- | --- |
| Draft → Post, stock, AR, tax, GL | PINT-AE XML generation and schema validation |
| PINT-AE **data completeness** on the document | Digital signature, Peppol AS4, FTA TDD |
| Store UUID, exchange timestamps, status, errors | Network delivery and buyer exchange |
| Credit note as the only correction of a posted/exchanged invoice | Re-submit / reject handling on the network |

Never implement Peppol AS4, OpenPeppol PKI, or MoF accreditation inside Plumbit. Never call an
ASP from `erp/sales_invoices/service.py`. Zoho Books / TallyPrime remain competitor ERPs —
optional **ASP adapters**, not a second ledger.

### Provider abstraction

```text
SalesInvoiceService.post()
  → commit ledger (stock + AR + tax + GL)
  → outbox EinvoiceSubmitRequested
Workers
  → EinvoiceProvider.submit(canonical_payload)
  → persist uuid, exchanged_at, status
Inbound webhook
  → EinvoiceProvider.verify_signature
  → erp service creates DRAFT purchase invoice (no silent post)
```

Canonical payload is **ours**, mapped from posted invoice fields — not a Zoho Books invoice
object and not Tally XML. Each adapter (`zoho.py`, `tally.py`, `generic_peppol_asp.py`)
translates to that vendor’s API. Tenant config selects the provider; swapping ASPs must not
change document models.

If a named vendor has no third-party ERP API, the generic ASP adapter is the default and
Zoho/Tally stay optional behind the same interface.

Status APIs live under `erp/` (on the document). Adapters live only under
`app/integrations/einvoicing/`.

### Data required before `submit_einvoice`

On tenant and on customer/supplier:

```text
trn  tin  peppol_participant_id  digital_location / digital_identity
free_zone_number (when applicable)  address city (PINT-AE)
```

On invoice / credit-note lines and headers:

```text
allowance / charge reason codes whenever discount or extra charge affects the amount
Unit Quantity Code (UQC / Peppol UOM map) on every goods line — extend inventory units
Tax category codes aligned to PINT-AE, not only internal STANDARD / ZERO_RATED / EXEMPT / OUT_OF_SCOPE
Buyer and seller Peppol IDs
```

On the document after exchange (append-only except designed status fields):

```text
einvoice_status     not_required | pending | submitted | exchanged | rejected | failed
einvoice_uuid
exchanged_at        (UTC)
asp_provider
asp_error_code / asp_error_message
```

### Lifecycle relative to posting

```text
DRAFT  →  POSTED (local ledger)  →  einvoice pending  →  exchanged
                                              ↘ rejected → credit note (+ new invoice)
```

- Drafts are never sent to an ASP (`EINVOICE_NOT_READY`).
- Posting must not wait on the ASP (`EINVOICE_ASP_UNAVAILABLE` is a worker/UI concern, not a
  failed post).
- Optional tenant flag `einvoicing_required`: when true, `send` / PDF-to-customer stays out of
  `available_actions` until `exchanged`.
- Submit is idempotent on document id + version; double-post to the ASP is
  `EINVOICE_ALREADY_EXCHANGED`.
- FTA 14-day reporting is the ASP’s job; Plumbit tracks `pending` older than a configurable SLA
  and surfaces it.
- An `exchanged` document is as immutable as `POSTED`. `EINVOICE_REJECTED` does not unlock the
  original row.

Inbound: ASP webhook → verified → `DRAFT` purchase invoice for matching against PO/GRN. Never
auto-post inbound e-bills. Inbound receive may reuse `erp.purchase_invoice.create`. Outbound
uses `erp.einvoice.submit` / `erp.einvoice.read`.

Workers include einvoice submit / poll / inbound webhook. Feature-flag the slice until the
adapter and document fields exist — do not publish empty OpenAPI stubs.

## 19. Sales and purchase cycles

Place Zoho/Odoo trading features in these slices. Do not invent a seventh top-level module.

**Sales:** Quote → Sales order → Delivery note → Sales invoice → Customer payment → Credit note

**Purchase:** Purchase order → GRN → Purchase invoice → Supplier payment → Debit note

Quotations already ship. Later slices follow this order so stock and tax have somewhere to
post. Accounting (chart of accounts, journals, AR, AP) comes after the documents that hit it.
E-invoicing ASP adapters come after posted sales invoices and credit notes exist.

## 20. Posting atomicity, branch, and outbox

Posting atomicity: stock + AR/AP + tax + GL succeed or roll back together in one database
transaction. Side effects (notifications, PDF, AI, ASP submit) go through the transactional
outbox **after** that commit. The outbox is not a substitute for the posting transaction.

Branch: documents may carry `branch_id` for defaults and reporting. Tenant isolation remains
session-derived `tenant_id`.

Rate-limit post, payment and e-invoice submit endpoints per tenant (configuration, not a
hardcoded router constant).

## 21. Tenant operational settings

These are first-class tenant **columns**, not JSONB extras, with dedicated permissions and
audit on change. Today `TenantSettings` only has profile fields plus `quotation_requires_approval`
— document the operational columns so they are added as columns when the slice is built:

```text
allow_negative_stock    default false     identity.organization.update
lock_date               date or null      erp.period.lock (or identity.organization.update until then)
hard_lock_date          date or null      erp.period.lock
einvoicing_required     default false     identity.organization.update
asp_provider_id         tenant-selected   identity.organization.update (credentials stay server-only)
peppol_participant_id, tin, digital identity   on tenant (public identifiers, not secrets)
```

Do not store ASP API keys on the tenant row returned to the client. Server-only secrets live
in configuration / a secrets manager, keyed by tenant + provider.

## 22. Dependency direction

```text
Module Router → Service → Repository → Model → Database
```

Allowed: any module may depend on `app/common/` and on another module's **service**.

Forbidden: `Models → Services`, `Models → Router`, `Repositories → Router`, one module
importing another module's models or repositories, module business logic living in
`app/common/`, circular imports between modules, and business modules importing
`app/integrations/einvoicing/` adapters except through the provider interface used by workers.
