"""Preferred-flag demotion for supplier catalog rows."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient

from app.db.session import async_session_factory
from app.erp.supplier_products.schemas import SupplierProductCreate, SupplierProductUpdate
from app.erp.supplier_products.service import SupplierProductService
from tests.api.erp.supplier_products.test_routes import (
    _create_catalog,
    _create_product,
    _create_supplier,
)
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_promoting_preferred_sku_demotes_incumbent(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    supplier = await _create_supplier(client, headers)
    product = await _create_product(client, headers)
    first = await _create_catalog(
        client,
        headers,
        supplier_id=str(supplier["id"]),
        supplier_sku="PREF-A",
        product_id=str(product["id"]),
        is_preferred=True,
    )
    second = await _create_catalog(
        client,
        headers,
        supplier_id=str(supplier["id"]),
        supplier_sku="PREF-B",
        product_id=str(product["id"]),
        is_preferred=True,
    )
    assert first["status_code"] == 201, first["text"]
    assert second["status_code"] == 201, second["text"]
    assert second["body"]["data"]["is_preferred"] is True
    fetched = await client.get(
        f"/api/v1/supplier-products/{first['body']['data']['id']}",
        headers=headers,
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["data"]["is_preferred"] is False


@pytest.mark.asyncio
async def test_promoting_preferred_supplier_demotes_incumbent(client: AsyncClient) -> None:
    tenant_id, email, password = await provision_admin()
    headers = await login_headers(client, tenant_id, email, password)
    supplier_a = await _create_supplier(client, headers, name="Vendor A")
    supplier_b = await _create_supplier(client, headers, name="Vendor B")
    product = await _create_product(client, headers)
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    actor_user_id = UUID(me.json()["data"]["id"])
    tenant_uuid = UUID(tenant_id)
    async with async_session_factory() as session:
        service = SupplierProductService(session)
        first = await service.create(
            tenant_uuid,
            SupplierProductCreate(
                supplier_id=UUID(str(supplier_a["id"])),
                product_id=UUID(str(product["id"])),
                supplier_sku="A-1",
                supplier_item_name="A item",
                is_preferred_supplier=True,
            ),
            actor_user_id=actor_user_id,
        )
        second = await service.create(
            tenant_uuid,
            SupplierProductCreate(
                supplier_id=UUID(str(supplier_b["id"])),
                product_id=UUID(str(product["id"])),
                supplier_sku="B-1",
                supplier_item_name="B item",
                is_preferred_supplier=True,
            ),
            actor_user_id=actor_user_id,
        )
        demoted = await service.get(tenant_uuid, first.id)
        assert second.is_preferred_supplier is True
        assert demoted.is_preferred_supplier is False
        await service.update(
            tenant_uuid,
            first.id,
            SupplierProductUpdate(is_preferred_supplier=True),
            actor_user_id=actor_user_id,
        )
        first_again = await service.get(tenant_uuid, first.id)
        second_again = await service.get(tenant_uuid, second.id)
        assert first_again.is_preferred_supplier is True
        assert second_again.is_preferred_supplier is False
