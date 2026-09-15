"""Customer create numbering and payload defaults."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import login_headers, provision_admin


async def _currency_id(client: AsyncClient, headers: dict[str, str]) -> str:
    currencies = await client.get("/api/v1/currencies?is_base=true", headers=headers)
    assert currencies.status_code == 200, currencies.text
    return str(currencies.json()["data"][0]["id"])


def _assert_party_code(code: str) -> None:
    assert len(code) == 3
    assert code.isalnum()
    assert code == code.upper()


@pytest.mark.asyncio
async def test_customer_code_is_auto_generated_when_omitted(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    currency_id = await _currency_id(client, headers)
    created = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": "Acme Global Motors",
            "tax_treatment": "UNREGISTERED",
            "currency_id": currency_id,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["code"] == "AGM"

    second = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": "Acme Global Manufacturing",
            "tax_treatment": "UNREGISTERED",
            "currency_id": currency_id,
            "code": "",
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["data"]["code"] == "AGN"

    explicit = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": f"Gamma {uuid4().hex[:8]}",
            "code": "G99",
            "tax_treatment": "UNREGISTERED",
            "currency_id": currency_id,
        },
    )
    assert explicit.status_code == 201, explicit.text
    assert explicit.json()["data"]["code"] == "G99"

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
    _assert_party_code(third_auto.json()["data"]["code"])
    assert third_auto.json()["data"]["code"] not in {"AGM", "AGN", "G99"}


@pytest.mark.asyncio
async def test_customer_code_rejects_hyphenated_or_long_values(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    currency_id = await _currency_id(client, headers)
    rejected = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": "Acme",
            "code": "CUS202601",
            "tax_treatment": "UNREGISTERED",
            "currency_id": currency_id,
        },
    )
    assert rejected.status_code == 422, rejected.text
