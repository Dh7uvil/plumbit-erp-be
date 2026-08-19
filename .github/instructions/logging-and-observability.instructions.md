---
description: Structured request logging, audit trails, health checks and performance guardrails.
applyTo: "app/**"
---

# Logging and Observability

## Structured logging

Logging is structured (machine-parseable), configured once in `app/core/logging.py`. Every
request log entry should carry:

```text
request_id  tenant_id  user_id  method  path  status_code  duration
```

`request_id` is generated in middleware and propagated so a single request can be traced
across services and background jobs.

## Never log

```text
passwords            API secrets
access tokens        credit card data
refresh tokens       sensitive financial credentials
```

Redact these at the logging layer rather than trusting call sites. Do not log full request
bodies for authentication or payment endpoints.

## Audit logging

ERP systems must maintain audit trails. Record for every meaningful change:

```text
tenant_id  user_id  action  module  entity_type  entity_id
old_values  new_values  ip_address  user_agent  created_at
```

Example entry:

```text
User: Dhruvil     Action: UPDATE     Entity: Sales Order     Entity ID: ...
Old Status: draft → New Status: approved
```

Audit logs are written by services (where the business meaning is known), not by repositories.
They are append-only and must not be editable by normal users. Any endpoint that changes state
— create, update, status transition, approval, posting, deletion — emits an audit record.

## Health checks

```text
GET /health        liveness of the process
GET /health/live   liveness probe
GET /health/ready  readiness — verifies database, Redis and required external infrastructure
```

Health endpoints must not expose sensitive diagnostic information such as connection strings,
versions of internal components or credentials.

## Performance guardrails

Avoid:

```text
N+1 queries          Loading entire tables            Repeated external API calls
Unbounded queries    Large synchronous operations
```

Use:

```text
pagination  selectinload  joinedload  indexes  caching  background jobs  bulk operations
```

Add indexes for commonly filtered fields:

```text
tenant_id  status  created_at  updated_at  document_number  foreign keys
```

Query patterns that fan out per row in a loop are a defect, not a style preference — load
relationships eagerly or batch the lookup.
