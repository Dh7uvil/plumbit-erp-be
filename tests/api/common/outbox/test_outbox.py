"""Outbox enqueue, claim, backoff, and admin API tests."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.common.outbox.dispatcher import dispatch_one
from app.common.outbox.handlers import clear as clear_handlers
from app.common.outbox.handlers import register as register_handler
from app.common.outbox.models import OutboxEvent
from app.common.outbox.service import OutboxService
from app.common.schemas.pagination import PageParams
from app.common.utils.datetime import utcnow
from app.core.enums import OutboxStatus
from app.db.session import async_session_factory, transaction
from tests.conftest import login_headers, provision_admin


@pytest.mark.asyncio
async def test_enqueue_rollback_leaves_no_event() -> None:
    tenant_id, _, _ = await provision_admin()
    tenant_uuid = UUID(tenant_id)
    aggregate_id = uuid4()
    async with async_session_factory() as session:
        try:
            async with transaction(session):
                await OutboxService(session).enqueue(
                    tenant_uuid,
                    event_type="test.ping",
                    aggregate_type="test",
                    aggregate_id=aggregate_id,
                )
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass

    async with async_session_factory() as session:
        _rows, total = await OutboxService(session).list(tenant_uuid, page=PageParams())
        assert total == 0


@pytest.mark.asyncio
async def test_dedupe_key_enqueues_once() -> None:
    tenant_id, _, _ = await provision_admin()
    tenant_uuid = UUID(tenant_id)
    aggregate_id = uuid4()
    async with async_session_factory() as session, transaction(session):
        service = OutboxService(session)
        first = await service.enqueue(
            tenant_uuid,
            event_type="test.ping",
            aggregate_type="test",
            aggregate_id=aggregate_id,
            dedupe_key="once",
        )
        second = await service.enqueue(
            tenant_uuid,
            event_type="test.ping",
            aggregate_type="test",
            aggregate_id=aggregate_id,
            dedupe_key="once",
        )
        assert first.id == second.id
    async with async_session_factory() as session:
        _rows, total = await OutboxService(session).list(
            tenant_uuid, page=PageParams(), event_type="test.ping"
        )
        assert total == 1


@pytest.mark.asyncio
async def test_concurrent_claim_returns_disjoint_sets() -> None:
    tenant_id, _, _ = await provision_admin()
    tenant_uuid = UUID(tenant_id)
    async with async_session_factory() as session, transaction(session):
        service = OutboxService(session)
        for _ in range(6):
            await service.enqueue(
                tenant_uuid,
                event_type="test.ping",
                aggregate_type="test",
                aggregate_id=uuid4(),
            )

    async with (
        async_session_factory() as s1,
        async_session_factory() as s2,
        s1.begin(),
        s2.begin(),
    ):
        claimed1 = await OutboxService(s1).claim(limit=3, worker_id="w1", tenant_id=tenant_uuid)
        claimed2 = await OutboxService(s2).claim(limit=3, worker_id="w2", tenant_id=tenant_uuid)
        ids1 = {row.id for row in claimed1}
        ids2 = {row.id for row in claimed2}
        assert len(ids1) == 3
        assert len(ids2) == 3
        assert ids1.isdisjoint(ids2)


@pytest.mark.asyncio
async def test_handler_failure_reaches_dead() -> None:
    tenant_id, _, _ = await provision_admin()
    tenant_uuid = UUID(tenant_id)

    async def boom(_event: OutboxEvent) -> None:
        raise RuntimeError("nope")

    register_handler("test.fail", boom)
    try:
        async with async_session_factory() as session, transaction(session):
            row = await OutboxService(session).enqueue(
                tenant_uuid,
                event_type="test.fail",
                aggregate_type="test",
                aggregate_id=uuid4(),
                max_attempts=3,
            )
            event_id = row.id

        for _ in range(3):
            async with async_session_factory() as session, transaction(session):
                claimed = await OutboxService(session).claim(
                    limit=1, worker_id="w1", tenant_id=tenant_uuid
                )
                assert len(claimed) == 1
                assert claimed[0].id == event_id
            await dispatch_one(event_id)
            async with async_session_factory() as session, transaction(session):
                row = await OutboxService(session).repo.get(tenant_uuid, event_id)
                assert row is not None
                row.available_at = utcnow()

        async with async_session_factory() as session:
            row = await OutboxService(session).repo.get(tenant_uuid, event_id)
            assert row is not None
            assert row.status == OutboxStatus.DEAD.value
            assert row.attempts == 3
    finally:
        clear_handlers()


@pytest.mark.asyncio
async def test_unknown_event_type_goes_dead_not_done() -> None:
    tenant_id, _, _ = await provision_admin()
    tenant_uuid = UUID(tenant_id)
    async with async_session_factory() as session, transaction(session):
        row = await OutboxService(session).enqueue(
            tenant_uuid,
            event_type="test.unknown",
            aggregate_type="test",
            aggregate_id=uuid4(),
        )
        event_id = row.id

    async with async_session_factory() as session, transaction(session):
        claimed = await OutboxService(session).claim(limit=1, worker_id="w1", tenant_id=tenant_uuid)
        assert [row.id for row in claimed] == [event_id]
    await dispatch_one(event_id)
    async with async_session_factory() as session:
        row = await OutboxService(session).repo.get(tenant_uuid, event_id)
        assert row is not None
        assert row.status == OutboxStatus.DEAD.value
        assert "Unknown event_type" in (row.last_error or "")


@pytest.mark.asyncio
async def test_outbox_admin_list_retry_and_tenant_isolation(client: AsyncClient) -> None:
    tenant_a, email_a, password_a = await provision_admin()
    tenant_b, email_b, password_b = await provision_admin()
    headers_a = await login_headers(client, tenant_a, email_a, password_a)
    headers_b = await login_headers(client, tenant_b, email_b, password_b)
    tenant_uuid = UUID(tenant_a)
    async with async_session_factory() as session, transaction(session):
        row = await OutboxService(session).enqueue(
            tenant_uuid,
            event_type="test.ping",
            aggregate_type="test",
            aggregate_id=uuid4(),
        )
        event_id = row.id
        row.status = OutboxStatus.FAILED.value
        row.last_error = "temporary"

    listed = await client.get("/api/v1/outbox-events", headers=headers_a)
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == str(event_id) for item in listed.json()["data"])

    isolated = await client.get(f"/api/v1/outbox-events/{event_id}", headers=headers_b)
    assert isolated.status_code == 404
    assert isolated.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    retried = await client.post(f"/api/v1/outbox-events/{event_id}/retry", headers=headers_a)
    assert retried.status_code == 200, retried.text
    assert retried.json()["data"]["status"] == "PENDING"
