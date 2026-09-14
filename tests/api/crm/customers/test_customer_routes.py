"""Customer create numbering and payload defaults."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.common.utils.datetime import utcnow
from tests.conftest import login_headers, provision_admin


async def _currency_id(client: AsyncClient, headers: dict[str, str]) -> str:
    currencies = await client.get("/api/v1/currencies?is_base=true", headers=headers)
    assert currencies.status_code == 200, currencies.text
    return str(currencies.json()["data"][0]["id"])


@pytest.mark.asyncio
async def test_customer_code_is_auto_generated_when_omitted(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    currency_id = await _currency_id(client, headers)
    year = utcnow().year
    created = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": f"Acme {uuid4().hex[:8]}",
            "tax_treatment": "UNREGISTERED",
            "currency_id": currency_id,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["code"] == f"CUS{year}01"

    second = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": f"Beta {uuid4().hex[:8]}",
            "tax_treatment": "UNREGISTERED",
            "currency_id": currency_id,
            "code": "",
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["data"]["code"] == f"CUS{year}02"

    explicit = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": f"Gamma {uuid4().hex[:8]}",
            "code": f"C-{uuid4().hex[:8]}",
            "tax_treatment": "UNREGISTERED",
            "currency_id": currency_id,
        },
    )
    assert explicit.status_code == 201, explicit.text
    assert explicit.json()["data"]["code"].startswith("C-")

    third_auto = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": f"Delta {uuid4().hex[:8]}",
            "tax_treatment": "UNREGISTERED",
            "currency_id": currency_id,
        },
    )
    assert third_auto.status_code == 201, third_auto.text
    assert third_auto.json()["data"]["code"] == f"CUS{year}03"
