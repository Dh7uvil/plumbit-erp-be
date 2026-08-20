"""Organization settings: current tenant, branches, and departments."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import IDENTITY_MODULE
from app.auth.models import Address, Branch, Department, Tenant, User
from app.auth.org_repository import OrganizationRepository
from app.auth.repository import AccessRepository
from app.auth.schemas import (
    AddressPayload,
    AddressResponse,
    BranchCreate,
    BranchResponse,
    BranchSummary,
    BranchUpdate,
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
    TenantCurrentResponse,
    TenantCurrentUpdate,
    TenantSettings,
    UserSummary,
)
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter
from app.core.enums import AddressType, AuditAction, BranchStatus
from app.core.exceptions import DuplicateResourceError, ResourceNotFoundError, ValidationError
from app.db.session import transaction

_SETTINGS_FIELDS = (
    "industry",
    "website",
    "contact_email",
    "phone",
    "founded",
    "fiscal_year_start",
    "default_currency",
    "headquarters",
)


def _address_values(payload: AddressPayload) -> dict[str, object]:
    return payload.model_dump(exclude_none=False)


def _address_has_values(payload: AddressPayload) -> bool:
    return any(value is not None for value in _address_values(payload).values())


def _address_response(address: Address | None) -> AddressResponse | None:
    if address is None:
        return None
    return AddressResponse.model_validate(address)


def _branch_snapshot(branch: Branch) -> dict[str, object]:
    return {
        "id": branch.id,
        "name": branch.name,
        "code": branch.code,
        "status": branch.status,
        "phone": branch.phone,
        "timezone": branch.timezone,
        "address_id": branch.address_id,
    }


def _department_snapshot(department: Department) -> dict[str, object]:
    return {
        "id": department.id,
        "name": department.name,
        "code": department.code,
        "branch_id": department.branch_id,
        "manager_id": department.manager_id,
    }


class OrganizationService:
    """Tenant, branch, and department use cases."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.access = AccessRepository(session)
        self.org = OrganizationRepository(session)
        self.audit = AuditWriter(session)

    async def get_current_tenant(self, tenant_id: UUID) -> TenantCurrentResponse:
        tenant = await self._require_tenant(tenant_id)
        return await self._tenant_response(tenant)

    async def update_current_tenant(
        self,
        tenant_id: UUID,
        payload: TenantCurrentUpdate,
        *,
        actor_user_id: UUID,
    ) -> TenantCurrentResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            tenant = await self._require_tenant(tenant_id)
            old_values = self._tenant_snapshot(tenant)
            if "name" in values:
                tenant.name = values["name"]
            if "timezone" in values and values["timezone"] is not None:
                tenant.timezone = values["timezone"]
            settings = TenantSettings.model_validate(tenant.settings or {})
            settings_update = {key: values[key] for key in _SETTINGS_FIELDS if key in values}
            if settings_update:
                tenant.settings = TenantSettings.model_validate(
                    {**settings.model_dump(), **settings_update}
                ).model_dump(mode="json")
            await self.session.flush()
            await self.session.refresh(tenant)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="tenant",
                entity_id=tenant.id,
                old_values=old_values,
                new_values=self._tenant_snapshot(tenant),
            )
            return await self._tenant_response(tenant)

    async def list_branches(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
    ) -> tuple[list[BranchResponse], int]:
        filters = {"status": status} if status is not None else None
        branches, total = await self.org.list_branches(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
        )
        responses = await self._branch_responses(tenant_id, list(branches))
        return responses, total

    async def create_branch(
        self,
        tenant_id: UUID,
        payload: BranchCreate,
        *,
        actor_user_id: UUID,
    ) -> BranchResponse:
        async with transaction(self.session):
            try:
                address_id = await self._upsert_address(tenant_id, None, payload.address)
                branch = await self.org.create_branch(
                    tenant_id,
                    {
                        "name": payload.name,
                        "code": payload.code,
                        "status": payload.status.value,
                        "phone": payload.phone,
                        "timezone": payload.timezone,
                        "address_id": address_id,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("A branch with this code already exists") from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=IDENTITY_MODULE,
                entity_type="branch",
                entity_id=branch.id,
                new_values=_branch_snapshot(branch),
            )
            await self.session.refresh(branch)
            return (await self._branch_responses(tenant_id, [branch]))[0]

    async def get_branch(self, tenant_id: UUID, branch_id: UUID) -> BranchResponse:
        branch = await self._require_branch(tenant_id, branch_id)
        return (await self._branch_responses(tenant_id, [branch]))[0]

    async def update_branch(
        self,
        tenant_id: UUID,
        branch_id: UUID,
        payload: BranchUpdate,
        *,
        actor_user_id: UUID,
    ) -> BranchResponse:
        values = payload.model_dump(exclude_unset=True)
        address_payload = values.pop("address", None)
        if "status" in values and values["status"] is not None:
            values["status"] = str(values["status"])
        async with transaction(self.session):
            branch = await self._require_branch(tenant_id, branch_id)
            old_values = _branch_snapshot(branch)
            if address_payload is not None:
                values["address_id"] = await self._upsert_address(
                    tenant_id,
                    branch.address_id,
                    AddressPayload.model_validate(address_payload),
                )
            for name, value in values.items():
                setattr(branch, name, value)
            try:
                await self.session.flush()
            except IntegrityError as exc:
                raise DuplicateResourceError("A branch with this code already exists") from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="branch",
                entity_id=branch.id,
                old_values=old_values,
                new_values=_branch_snapshot(branch),
            )
            await self.session.refresh(branch)
            return (await self._branch_responses(tenant_id, [branch]))[0]

    async def delete_branch(
        self,
        tenant_id: UUID,
        branch_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> BranchResponse:
        async with transaction(self.session):
            branch = await self._require_branch(tenant_id, branch_id)
            if await self.org.count_departments_for_branch(tenant_id, branch_id) > 0:
                raise ValidationError("Cannot delete a branch that still has departments")
            if await self.org.count_employees_for_branch(tenant_id, branch_id) > 0:
                raise ValidationError("Cannot delete a branch that still has employees")
            response = (await self._branch_responses(tenant_id, [branch]))[0]
            await self.org.soft_delete_branch(tenant_id, branch_id)
            if branch.address_id is not None:
                await self.org.addresses.soft_delete(tenant_id, branch.address_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=IDENTITY_MODULE,
                entity_type="branch",
                entity_id=branch.id,
                old_values=_branch_snapshot(branch),
            )
            return response

    async def list_departments(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        branch_id: UUID | None = None,
    ) -> tuple[list[DepartmentResponse], int]:
        filters: dict[str, object] | None = {"branch_id": branch_id} if branch_id else None
        departments, total = await self.org.list_departments(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
        )
        responses = await self._department_responses(tenant_id, list(departments))
        return responses, total

    async def create_department(
        self,
        tenant_id: UUID,
        payload: DepartmentCreate,
        *,
        actor_user_id: UUID,
    ) -> DepartmentResponse:
        async with transaction(self.session):
            await self._require_branch(tenant_id, payload.branch_id)
            await self._require_manager(tenant_id, payload.manager_id)
            try:
                department = await self.org.create_department(
                    tenant_id,
                    {
                        "name": payload.name,
                        "code": payload.code,
                        "branch_id": payload.branch_id,
                        "manager_id": payload.manager_id,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("A department with this code already exists") from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=IDENTITY_MODULE,
                entity_type="department",
                entity_id=department.id,
                new_values=_department_snapshot(department),
            )
            await self.session.refresh(department)
            return (await self._department_responses(tenant_id, [department]))[0]

    async def get_department(self, tenant_id: UUID, department_id: UUID) -> DepartmentResponse:
        department = await self._require_department(tenant_id, department_id)
        return (await self._department_responses(tenant_id, [department]))[0]

    async def update_department(
        self,
        tenant_id: UUID,
        department_id: UUID,
        payload: DepartmentUpdate,
        *,
        actor_user_id: UUID,
    ) -> DepartmentResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            department = await self._require_department(tenant_id, department_id)
            old_values = _department_snapshot(department)
            if "branch_id" in values and values["branch_id"] is not None:
                await self._require_branch(tenant_id, values["branch_id"])
            if "manager_id" in values:
                await self._require_manager(tenant_id, values["manager_id"])
            for name, value in values.items():
                setattr(department, name, value)
            try:
                await self.session.flush()
            except IntegrityError as exc:
                raise DuplicateResourceError("A department with this code already exists") from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="department",
                entity_id=department.id,
                old_values=old_values,
                new_values=_department_snapshot(department),
            )
            await self.session.refresh(department)
            return (await self._department_responses(tenant_id, [department]))[0]

    async def delete_department(
        self,
        tenant_id: UUID,
        department_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> DepartmentResponse:
        async with transaction(self.session):
            department = await self._require_department(tenant_id, department_id)
            if await self.org.count_employees_for_department(tenant_id, department_id) > 0:
                raise ValidationError("Cannot delete a department that still has employees")
            response = (await self._department_responses(tenant_id, [department]))[0]
            await self.org.soft_delete_department(tenant_id, department_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=IDENTITY_MODULE,
                entity_type="department",
                entity_id=department.id,
                old_values=_department_snapshot(department),
            )
            return response

    async def _require_tenant(self, tenant_id: UUID) -> Tenant:
        tenant = await self.access.get_tenant(tenant_id)
        if tenant is None:
            raise ResourceNotFoundError("Tenant not found")
        return tenant

    async def _require_branch(self, tenant_id: UUID, branch_id: UUID) -> Branch:
        branch = await self.org.get_branch(tenant_id, branch_id)
        if branch is None:
            raise ResourceNotFoundError("Branch not found")
        return branch

    async def _require_department(self, tenant_id: UUID, department_id: UUID) -> Department:
        department = await self.org.get_department(tenant_id, department_id)
        if department is None:
            raise ResourceNotFoundError("Department not found")
        return department

    async def _require_manager(self, tenant_id: UUID, manager_id: UUID | None) -> User | None:
        if manager_id is None:
            return None
        user = await self.access.get_user(tenant_id, manager_id)
        if user is None:
            raise ResourceNotFoundError("Manager not found")
        return user

    async def _upsert_address(
        self,
        tenant_id: UUID,
        address_id: UUID | None,
        payload: AddressPayload | None,
    ) -> UUID | None:
        if payload is None:
            return address_id
        values = _address_values(payload)
        if address_id is None:
            if not _address_has_values(payload):
                return None
            address = await self.org.create_address(
                tenant_id,
                values,
                address_type=AddressType.BRANCH,
            )
            return address.id
        updated = await self.org.update_address(tenant_id, address_id, values)
        if updated is None:
            address = await self.org.create_address(
                tenant_id,
                values,
                address_type=AddressType.BRANCH,
            )
            return address.id
        return updated.id

    async def _tenant_response(self, tenant: Tenant) -> TenantCurrentResponse:
        settings = TenantSettings.model_validate(tenant.settings or {})
        return TenantCurrentResponse(
            id=tenant.id,
            name=tenant.name,
            code=tenant.code,
            timezone=tenant.timezone,
            status=tenant.status,
            industry=settings.industry,
            website=settings.website,
            contact_email=settings.contact_email,
            phone=settings.phone,
            founded=settings.founded,
            fiscal_year_start=settings.fiscal_year_start,
            default_currency=settings.default_currency,
            headquarters=settings.headquarters,
            users_count=await self.org.count_users(tenant.id),
            departments_count=await self.org.count_departments(tenant.id),
            branches_count=await self.org.count_branches(tenant.id),
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
        )

    def _tenant_snapshot(self, tenant: Tenant) -> dict[str, object]:
        return {
            "id": tenant.id,
            "name": tenant.name,
            "timezone": tenant.timezone,
            "settings": tenant.settings,
        }

    async def _branch_responses(
        self,
        tenant_id: UUID,
        branches: list[Branch],
    ) -> list[BranchResponse]:
        address_ids = [branch.address_id for branch in branches if branch.address_id is not None]
        addresses = await self.org.get_addresses_by_ids(tenant_id, address_ids)
        counts = await self.org.count_employees_by_branch(
            tenant_id,
            [branch.id for branch in branches],
        )
        return [
            BranchResponse(
                id=branch.id,
                tenant_id=branch.tenant_id,
                name=branch.name,
                code=branch.code,
                status=BranchStatus(branch.status),
                phone=branch.phone,
                timezone=branch.timezone,
                address=_address_response(addresses.get(branch.address_id))
                if branch.address_id is not None
                else None,
                employee_count=counts.get(branch.id, 0),
                created_at=branch.created_at,
                updated_at=branch.updated_at,
            )
            for branch in branches
        ]

    async def _department_responses(
        self,
        tenant_id: UUID,
        departments: list[Department],
    ) -> list[DepartmentResponse]:
        branch_ids = [department.branch_id for department in departments]
        manager_ids = [
            department.manager_id for department in departments if department.manager_id is not None
        ]
        branches = await self.org.get_branches_by_ids(tenant_id, branch_ids)
        managers = await self.org.get_users_by_ids(tenant_id, manager_ids)
        counts = await self.org.count_employees_by_department(
            tenant_id,
            [department.id for department in departments],
        )
        return [
            DepartmentResponse(
                id=department.id,
                tenant_id=department.tenant_id,
                name=department.name,
                code=department.code,
                branch_id=department.branch_id,
                branch=BranchSummary.model_validate(branches[department.branch_id])
                if department.branch_id in branches
                else None,
                manager_id=department.manager_id,
                manager=UserSummary.model_validate(managers[department.manager_id])
                if department.manager_id is not None and department.manager_id in managers
                else None,
                employee_count=counts.get(department.id, 0),
                created_at=department.created_at,
                updated_at=department.updated_at,
            )
            for department in departments
        ]
