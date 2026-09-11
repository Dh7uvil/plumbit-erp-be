"""Shipment compose and tracking. Moves no stock and writes no ledger entry."""

from __future__ import annotations

import builtins
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import (
    INVENTORY_MODULE,
    SHIPMENT_CLOSE,
    SHIPMENT_DELETE,
    SHIPMENT_DISPATCH,
    SHIPMENT_UPDATE,
)
from app.auth.org_service import OrganizationService
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.schemas.related_documents import RelatedDocumentRef
from app.common.services.audit import AuditWriter
from app.common.utils.datetime import today_in_timezone
from app.core.enums import (
    AuditAction,
    DocumentType,
    Incoterm,
    ShipmentStatus,
    ShipmentType,
    TransportMode,
)
from app.core.exceptions import (
    DocumentStaleError,
    InvalidStatusTransitionError,
    ResourceNotFoundError,
)
from app.core.permissions import has_permission
from app.crm.customers.service import CustomerService
from app.db.session import transaction
from app.erp.accounting.fiscal import year_for
from app.erp.accounting.service import DocumentSequenceService
from app.inventory_management.delivery_notes.service import DeliveryNoteService
from app.inventory_management.shipments.models import Shipment
from app.inventory_management.shipments.repository import ShipmentRepository
from app.inventory_management.shipments.schemas import (
    ShipmentCreate,
    ShipmentResponse,
    ShipmentTrackingUpdate,
    ShipmentUpdate,
)
from app.inventory_management.shipments.workflow import (
    assert_editable,
    assert_trackable,
    next_status,
    transition_actions,
)

_SERIES = "SHP"
_ACTION_PERMISSIONS: dict[str, str] = {
    "dispatch": SHIPMENT_DISPATCH,
    "arrive": SHIPMENT_UPDATE,
    "close": SHIPMENT_CLOSE,
    "cancel": SHIPMENT_UPDATE,
}
_TRACKING_FIELDS = (
    "carrier_name",
    "vessel_or_flight_no",
    "voyage_number",
    "bl_awb_number",
    "bl_awb_date",
    "etd",
    "eta",
    "actual_departure_date",
    "actual_arrival_date",
)


class ShipmentService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        actor_permissions: frozenset[str] = frozenset(),
    ) -> None:
        self.session = session
        self.actor_permissions = actor_permissions
        self.repo = ShipmentRepository(session)
        self.delivery_notes = DeliveryNoteService(session, actor_permissions=actor_permissions)
        self.customers = CustomerService(session)
        self.org = OrganizationService(session)
        self.sequences = DocumentSequenceService(session)
        self.audit = AuditWriter(session)

    async def list(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
        shipment_type: str | None = None,
        transport_mode: str | None = None,
    ) -> tuple[list[ShipmentResponse], int]:
        filters: dict[str, object] = {}
        if status is not None:
            filters["status"] = status
        if shipment_type is not None:
            filters["shipment_type"] = shipment_type
        if transport_mode is not None:
            filters["transport_mode"] = transport_mode
        rows, total = await self.repo.list(
            tenant_id, page=page, common_filter=common_filter, filters=filters or None
        )
        return [self._to_response(row) for row in rows], total

    async def get(self, tenant_id: UUID, shipment_id: UUID) -> ShipmentResponse:
        row = await self._require(tenant_id, shipment_id)
        response = self._to_response(row)
        response.related_documents = await self._related_documents(tenant_id, row)
        return response

    async def delivery_note_is_shipped(self, tenant_id: UUID, delivery_note_id: UUID) -> bool:
        note = await self.delivery_notes._require(tenant_id, delivery_note_id)
        return note.shipment_id is not None

    async def create(
        self, tenant_id: UUID, payload: ShipmentCreate, *, actor_user_id: UUID
    ) -> ShipmentResponse:
        async with transaction(self.session):
            values = await self._header_values(tenant_id, payload)
            fiscal_year = await year_for(
                self.session, tenant_id, today_in_timezone(await self.org.get_timezone(tenant_id))
            )
            number = await self.sequences.allocate(
                tenant_id,
                document_type=DocumentType.SHIPMENT,
                series=_SERIES,
                fiscal_year=fiscal_year,
                prefix=_SERIES,
            )
            row = await self.repo.create(
                tenant_id,
                {
                    **values,
                    "document_number": number,
                    "status": ShipmentStatus.DRAFT.value,
                    "version": 1,
                    "created_by": actor_user_id,
                    "updated_by": actor_user_id,
                },
            )
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=INVENTORY_MODULE,
                entity_type="shipment",
                entity_id=row.id,
                new_values={"document_number": row.document_number},
            )
            return self._to_response(row)

    async def update(
        self,
        tenant_id: UUID,
        shipment_id: UUID,
        payload: ShipmentUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> ShipmentResponse:
        async with transaction(self.session):
            existing = await self._require(tenant_id, shipment_id, for_update=True)
            assert_editable(ShipmentStatus(existing.status))
            self._assert_version(existing, expected_version)
            merged = ShipmentCreate(
                shipment_type=payload.shipment_type or ShipmentType(existing.shipment_type),
                transport_mode=payload.transport_mode or TransportMode(existing.transport_mode),
                incoterm=payload.incoterm
                if payload.incoterm is not None
                else (Incoterm(existing.incoterm) if existing.incoterm else None),
                container_number=payload.container_number
                if payload.container_number is not None
                else existing.container_number,
                seal_number=payload.seal_number
                if payload.seal_number is not None
                else existing.seal_number,
                carrier_name=payload.carrier_name
                if payload.carrier_name is not None
                else existing.carrier_name,
                vessel_or_flight_no=payload.vessel_or_flight_no
                if payload.vessel_or_flight_no is not None
                else existing.vessel_or_flight_no,
                voyage_number=payload.voyage_number
                if payload.voyage_number is not None
                else existing.voyage_number,
                bl_awb_number=payload.bl_awb_number
                if payload.bl_awb_number is not None
                else existing.bl_awb_number,
                bl_awb_date=payload.bl_awb_date
                if payload.bl_awb_date is not None
                else existing.bl_awb_date,
                freight_forwarder_id=payload.freight_forwarder_id
                if payload.freight_forwarder_id is not None
                else existing.freight_forwarder_id,
                port_of_loading=payload.port_of_loading
                if payload.port_of_loading is not None
                else existing.port_of_loading,
                port_of_discharge=payload.port_of_discharge
                if payload.port_of_discharge is not None
                else existing.port_of_discharge,
                etd=payload.etd if payload.etd is not None else existing.etd,
                eta=payload.eta if payload.eta is not None else existing.eta,
                gross_weight=payload.gross_weight
                if payload.gross_weight is not None
                else existing.gross_weight,
                net_weight=payload.net_weight
                if payload.net_weight is not None
                else existing.net_weight,
                total_packages=payload.total_packages
                if payload.total_packages is not None
                else existing.total_packages,
                notes=payload.notes if payload.notes is not None else existing.notes,
            )
            values = await self._header_values(tenant_id, merged)
            values["updated_by"] = actor_user_id
            values["version"] = existing.version + 1
            updated = await self.repo.update(tenant_id, shipment_id, values)
            if updated is None:
                raise ResourceNotFoundError("Shipment not found")
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="shipment",
                entity_id=shipment_id,
            )
            return self._to_response(updated)

    async def delete(
        self,
        tenant_id: UUID,
        shipment_id: UUID,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> ShipmentResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, shipment_id, for_update=True)
            if ShipmentStatus(row.status) != ShipmentStatus.DRAFT:
                raise InvalidStatusTransitionError("Only draft shipments can be deleted")
            self._assert_version(row, expected_version)
            response = self._to_response(row)
            await self.repo.soft_delete(tenant_id, shipment_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=INVENTORY_MODULE,
                entity_type="shipment",
                entity_id=shipment_id,
            )
            return response

    async def dispatch(
        self, tenant_id: UUID, shipment_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> ShipmentResponse:
        return await self._transition(
            tenant_id,
            shipment_id,
            "dispatch",
            actor_user_id,
            expected_version,
            AuditAction.DISPATCH,
        )

    async def arrive(
        self, tenant_id: UUID, shipment_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> ShipmentResponse:
        return await self._transition(
            tenant_id, shipment_id, "arrive", actor_user_id, expected_version, AuditAction.ARRIVE
        )

    async def close(
        self, tenant_id: UUID, shipment_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> ShipmentResponse:
        return await self._transition(
            tenant_id, shipment_id, "close", actor_user_id, expected_version, AuditAction.CLOSE
        )

    async def cancel(
        self, tenant_id: UUID, shipment_id: UUID, *, actor_user_id: UUID, expected_version: int
    ) -> ShipmentResponse:
        return await self._transition(
            tenant_id, shipment_id, "cancel", actor_user_id, expected_version, AuditAction.CANCEL
        )

    async def update_tracking(
        self,
        tenant_id: UUID,
        shipment_id: UUID,
        payload: ShipmentTrackingUpdate,
        *,
        actor_user_id: UUID,
        expected_version: int,
    ) -> ShipmentResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, shipment_id, for_update=True)
            assert_trackable(ShipmentStatus(row.status))
            self._assert_version(row, expected_version)
            old_values = {name: getattr(row, name) for name in _TRACKING_FIELDS}
            values = payload.model_dump(exclude_unset=True, exclude={"version"})
            for name, value in values.items():
                setattr(row, name, value)
            if row.actual_departure_date is not None and ShipmentStatus(row.status) == (
                ShipmentStatus.DISPATCHED
            ):
                row.status = ShipmentStatus.IN_TRANSIT.value
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=INVENTORY_MODULE,
                entity_type="shipment",
                entity_id=shipment_id,
                old_values=old_values,
                new_values={name: getattr(row, name) for name in _TRACKING_FIELDS},
            )
            return self._to_response(row)

    async def attach_delivery_notes(
        self,
        tenant_id: UUID,
        shipment_id: UUID,
        delivery_note_ids: builtins.list[UUID],
        *,
        actor_user_id: UUID,
    ) -> ShipmentResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, shipment_id, for_update=True)
            if ShipmentStatus(row.status) in {ShipmentStatus.CLOSED, ShipmentStatus.CANCELLED}:
                raise InvalidStatusTransitionError("Cannot attach notes to a closed shipment")
            for note_id in delivery_note_ids:
                await self.delivery_notes.attach_shipment(tenant_id, note_id, row.id)
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.LINK,
                module=INVENTORY_MODULE,
                entity_type="shipment",
                entity_id=shipment_id,
                new_values={"delivery_note_ids": [str(item) for item in delivery_note_ids]},
            )
            return self._to_response(row)

    async def detach_delivery_note(
        self,
        tenant_id: UUID,
        shipment_id: UUID,
        delivery_note_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> ShipmentResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, shipment_id, for_update=True)
            await self.delivery_notes.detach_shipment(tenant_id, delivery_note_id, row.id)
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UNLINK,
                module=INVENTORY_MODULE,
                entity_type="shipment",
                entity_id=shipment_id,
                new_values={"delivery_note_id": str(delivery_note_id)},
            )
            return self._to_response(row)

    async def _transition(
        self,
        tenant_id: UUID,
        shipment_id: UUID,
        action: str,
        actor_user_id: UUID,
        expected_version: int,
        audit_action: AuditAction,
    ) -> ShipmentResponse:
        async with transaction(self.session):
            row = await self._require(tenant_id, shipment_id, for_update=True)
            self._assert_version(row, expected_version)
            target = next_status(ShipmentStatus(row.status), action)
            row.status = target.value
            row.version += 1
            row.updated_by = actor_user_id
            await self.session.flush()
            await self.session.refresh(row, attribute_names=["updated_at"])
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=audit_action,
                module=INVENTORY_MODULE,
                entity_type="shipment",
                entity_id=shipment_id,
            )
            return self._to_response(row)

    async def _header_values(self, tenant_id: UUID, payload: ShipmentCreate) -> dict[str, Any]:
        if payload.freight_forwarder_id is not None:
            await self.customers.get(tenant_id, payload.freight_forwarder_id)
        return {
            "shipment_type": payload.shipment_type.value,
            "transport_mode": payload.transport_mode.value,
            "incoterm": payload.incoterm.value if payload.incoterm else None,
            "container_number": payload.container_number,
            "seal_number": payload.seal_number,
            "carrier_name": payload.carrier_name,
            "vessel_or_flight_no": payload.vessel_or_flight_no,
            "voyage_number": payload.voyage_number,
            "bl_awb_number": payload.bl_awb_number,
            "bl_awb_date": payload.bl_awb_date,
            "freight_forwarder_id": payload.freight_forwarder_id,
            "port_of_loading": payload.port_of_loading,
            "port_of_discharge": payload.port_of_discharge,
            "etd": payload.etd,
            "eta": payload.eta,
            "gross_weight": payload.gross_weight,
            "net_weight": payload.net_weight,
            "total_packages": payload.total_packages,
            "notes": payload.notes,
        }

    def _to_response(self, row: Shipment) -> ShipmentResponse:
        status = ShipmentStatus(row.status)
        return ShipmentResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            document_number=row.document_number,
            status=status,
            version=row.version,
            shipment_type=ShipmentType(row.shipment_type),
            transport_mode=TransportMode(row.transport_mode),
            incoterm=Incoterm(row.incoterm) if row.incoterm else None,
            container_number=row.container_number,
            seal_number=row.seal_number,
            carrier_name=row.carrier_name,
            vessel_or_flight_no=row.vessel_or_flight_no,
            voyage_number=row.voyage_number,
            bl_awb_number=row.bl_awb_number,
            bl_awb_date=row.bl_awb_date,
            freight_forwarder_id=row.freight_forwarder_id,
            port_of_loading=row.port_of_loading,
            port_of_discharge=row.port_of_discharge,
            etd=row.etd,
            eta=row.eta,
            actual_departure_date=row.actual_departure_date,
            actual_arrival_date=row.actual_arrival_date,
            gross_weight=row.gross_weight,
            net_weight=row.net_weight,
            total_packages=row.total_packages,
            notes=row.notes,
            available_actions=self._available_actions(status),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _related_documents(
        self, tenant_id: UUID, row: Shipment
    ) -> builtins.list[RelatedDocumentRef]:
        related: builtins.list[RelatedDocumentRef] = []
        for note in await self.delivery_notes.repo.list_for_shipment(tenant_id, row.id):
            related.append(
                RelatedDocumentRef(
                    document_type=DocumentType.DELIVERY_NOTE.value,
                    document_id=note.id,
                    document_number=note.document_number,
                    status=note.status,
                    relationship="child",
                    document_date=note.document_date,
                )
            )
        return related

    def _available_actions(self, status: ShipmentStatus) -> builtins.list[str]:
        actions: builtins.list[str] = []
        for action in transition_actions(status):
            required = _ACTION_PERMISSIONS[action]
            if has_permission(self.actor_permissions, required):
                actions.append(action)
        if status == ShipmentStatus.DRAFT and has_permission(
            self.actor_permissions, SHIPMENT_DELETE
        ):
            actions.append("delete")
        return actions

    def _assert_version(self, row: Shipment, expected_version: int) -> None:
        if row.version != expected_version:
            raise DocumentStaleError(
                details={"current_version": row.version, "provided_version": expected_version}
            )

    async def _require(
        self, tenant_id: UUID, shipment_id: UUID, *, for_update: bool = False
    ) -> Shipment:
        row = await self.repo.get(tenant_id, shipment_id, for_update=for_update)
        if row is None:
            raise ResourceNotFoundError("Shipment not found")
        return row
