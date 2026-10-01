"""Cross-tenant isolation tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.integrations.agora.channels import conversation_channel_name
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_cross_tenant_conversation_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin(name=f"Tenant A {uuid4().hex[:6]}")
    tenant_b, email_b, password_b = await provision_admin(name=f"Tenant B {uuid4().hex[:6]}")
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)

    created = await client.post(
        "/api/v1/communication/conversations",
        headers=headers_a,
        json={"kind": "GROUP", "name": "Private A", "participant_user_ids": []},
    )
    assert created.status_code == 201, created.text
    conv_id = created.json()["data"]["id"]

    foreign = await client.get(
        f"/api/v1/communication/conversations/{conv_id}",
        headers=headers_b,
    )
    assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_channel_names_are_tenant_prefixed() -> None:
    from uuid import UUID

    t1 = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    t2 = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    conv = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    assert conversation_channel_name(t1, conv) != conversation_channel_name(t2, conv)
