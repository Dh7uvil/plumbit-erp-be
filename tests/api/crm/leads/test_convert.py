"""API tests for lead conversion."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_convert_lead_creates_customer_contact_and_opportunity(
    client: AsyncClient,
) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    suffix = uuid4().hex[:6]
    created = await client.post(
        "/api/v1/leads",
        headers=headers,
        json={
            "first_name": "Taylor",
            "last_name": f"Convert {suffix}",
            "company_name": f"Convert Co {suffix}",
            "email": f"taylor.{suffix}@example.com",
        },
    )
    assert created.status_code == 201, created.text
    lead = created.json()["data"]
    idempotency_key = f"lead-convert-{uuid4()}"

    convert_payload = {
        "new_customer": {"name": f"Convert Co {suffix}"},
        "contact": {
            "name": f"Taylor Convert {suffix}",
            "email": f"taylor.{suffix}@example.com",
            "is_primary": True,
        },
        "opportunity": {"create": True},
    }
    converted = await client.post(
        f"/api/v1/leads/{lead['id']}/convert",
        headers={
            **headers,
            "Idempotency-Key": idempotency_key,
            "If-Match": str(lead["version"]),
        },
        json=convert_payload,
    )
    assert converted.status_code == 201, converted.text
    body = converted.json()["data"]
    assert body["customer_id"]
    assert body["contact_id"]
    assert body["opportunity_id"]
    assert body["lead"]["status"] == "CONVERTED"
    assert body["lead"]["converted_customer_id"] == body["customer_id"]
    assert body["lead"]["converted_opportunity_id"] == body["opportunity_id"]

    replay = await client.post(
        f"/api/v1/leads/{lead['id']}/convert",
        headers={
            **headers,
            "Idempotency-Key": idempotency_key,
            "If-Match": str(lead["version"]),
        },
        json=convert_payload,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["data"]["opportunity_id"] == body["opportunity_id"]


@pytest.mark.asyncio
async def test_convert_lead_rejects_already_converted(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    created = await client.post(
        "/api/v1/leads",
        headers=headers,
        json={"company_name": f"Twice {uuid4().hex[:8]}"},
    )
    assert created.status_code == 201, created.text
    lead = created.json()["data"]
    payload = {
        "new_customer": {"name": lead["company_name"]},
        "contact": {"name": "Primary", "is_primary": True},
        "opportunity": {"create": False},
    }
    first = await client.post(
        f"/api/v1/leads/{lead['id']}/convert",
        headers={
            **headers,
            "Idempotency-Key": str(uuid4()),
            "If-Match": str(lead["version"]),
        },
        json=payload,
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        f"/api/v1/leads/{lead['id']}/convert",
        headers={
            **headers,
            "Idempotency-Key": str(uuid4()),
            "If-Match": str(first.json()["data"]["lead"]["version"]),
        },
        json=payload,
    )
    assert second.status_code == 422, second.text
    assert second.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_convert_lead_requires_idempotency_key(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    created = await client.post(
        "/api/v1/leads",
        headers=headers,
        json={"company_name": f"NoKey {uuid4().hex[:8]}"},
    )
    assert created.status_code == 201, created.text
    lead = created.json()["data"]
    response = await client.post(
        f"/api/v1/leads/{lead['id']}/convert",
        headers={**headers, "If-Match": "1"},
        json={
            "new_customer": {"name": lead["company_name"]},
            "contact": {"name": "Primary", "is_primary": True},
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
