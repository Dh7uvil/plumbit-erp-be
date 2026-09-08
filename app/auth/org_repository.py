"""Database access for addresses, branches, departments, and employees."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Address, Branch, Department, Employee, Tenant, User
from app.common.repositories.base import BaseRepository
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.utils.datetime import utcnow
from app.core.enums import AddressType

_EMPLOYEE_CODE_PREFIX = "EMP"


def next_employee_code_from_existing(existing_codes: Sequence[str], year: int) -> str:
    """Return the next ``EMP{year}{seq}`` code from existing codes for that year."""

    prefix = f"{_EMPLOYEE_CODE_PREFIX}{year}"
    highest = 0
    for code in existing_codes:
        if not code.startswith(prefix):
            continue
        suffix = code[len(prefix) :]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"{prefix}{highest + 1:02d}"


class OrganizationRepository:
    """Tenant-scoped queries for organization entities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.addresses = BaseRepository(
            session,
            Address,
            allowed_sort_fields=frozenset({"created_at", "updated_at"}),
        )
        self.branches = BaseRepository(
            session,
            Branch,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name", "code", "status"}),
            allowed_filter_fields=frozenset({"status"}),
            search_fields=frozenset({"name", "code"}),
        )
        self.departments = BaseRepository(
            session,
            Department,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name", "code"}),
            allowed_filter_fields=frozenset({"branch_id"}),
            search_fields=frozenset({"name", "code"}),
        )
        self.employees = BaseRepository(
            session,
            Employee,
            allowed_sort_fields=frozenset({"created_at", "updated_at", "employee_code", "status"}),
            allowed_filter_fields=frozenset({"status", "branch_id", "department_id"}),
            search_fields=frozenset({"employee_code", "designation"}),
        )

    async def get_address(self, tenant_id: UUID, address_id: UUID) -> Address | None:
        return await self.addresses.get(tenant_id, address_id)

    async def create_address(
        self,
        tenant_id: UUID,
        values: Mapping[str, object],
        *,
        address_type: AddressType = AddressType.BRANCH,
    ) -> Address:
        payload = dict(values)
        payload.setdefault("address_type", address_type.value)
        return await self.addresses.create(tenant_id, payload)

    async def update_address(
        self,
        tenant_id: UUID,
        address_id: UUID,
        values: Mapping[str, object],
    ) -> Address | None:
        return await self.addresses.update(tenant_id, address_id, values)

    async def get_branch(self, tenant_id: UUID, branch_id: UUID) -> Branch | None:
        return await self.branches.get(tenant_id, branch_id)

    async def list_branches(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Branch], int]:
        return await self.branches.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
        )

    async def create_branch(self, tenant_id: UUID, values: Mapping[str, object]) -> Branch:
        return await self.branches.create(tenant_id, values)

    async def update_branch(
        self,
        tenant_id: UUID,
        branch_id: UUID,
        values: Mapping[str, object],
    ) -> Branch | None:
        return await self.branches.update(tenant_id, branch_id, values)

    async def soft_delete_branch(self, tenant_id: UUID, branch_id: UUID) -> Branch | None:
        return await self.branches.soft_delete(tenant_id, branch_id)

    async def get_department(self, tenant_id: UUID, department_id: UUID) -> Department | None:
        return await self.departments.get(tenant_id, department_id)

    async def list_departments(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Department], int]:
        return await self.departments.list(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
        )

    async def create_department(self, tenant_id: UUID, values: Mapping[str, object]) -> Department:
        return await self.departments.create(tenant_id, values)

    async def update_department(
        self,
        tenant_id: UUID,
        department_id: UUID,
        values: Mapping[str, object],
    ) -> Department | None:
        return await self.departments.update(tenant_id, department_id, values)

    async def soft_delete_department(
        self,
        tenant_id: UUID,
        department_id: UUID,
    ) -> Department | None:
        return await self.departments.soft_delete(tenant_id, department_id)

    async def get_employee(self, tenant_id: UUID, employee_id: UUID) -> Employee | None:
        return await self.employees.get(tenant_id, employee_id)

    async def create_employee(self, tenant_id: UUID, values: Mapping[str, object]) -> Employee:
        return await self.employees.create(tenant_id, values)

    async def next_employee_code(self, tenant_id: UUID) -> str:
        """Allocate the next tenant-scoped ``EMP{year}{seq}`` code under a tenant lock."""

        year = utcnow().year
        prefix = f"{_EMPLOYEE_CODE_PREFIX}{year}"
        await self.session.execute(
            select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()
        )
        statement = select(Employee.employee_code).where(
            Employee.tenant_id == tenant_id,
            Employee.employee_code.like(f"{prefix}%"),
        )
        result = await self.session.execute(statement)
        return next_employee_code_from_existing(list(result.scalars().all()), year)

    async def update_employee(
        self,
        tenant_id: UUID,
        employee_id: UUID,
        values: Mapping[str, object],
    ) -> Employee | None:
        return await self.employees.update(tenant_id, employee_id, values)

    async def get_addresses_by_ids(
        self,
        tenant_id: UUID,
        address_ids: Sequence[UUID],
    ) -> dict[UUID, Address]:
        unique_ids = list(dict.fromkeys(address_ids))
        if not unique_ids:
            return {}
        statement = select(Address).where(
            Address.tenant_id == tenant_id,
            Address.id.in_(unique_ids),
            Address.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        return {row.id: row for row in result.scalars().all()}

    async def get_branches_by_ids(
        self,
        tenant_id: UUID,
        branch_ids: Sequence[UUID],
    ) -> dict[UUID, Branch]:
        unique_ids = list(dict.fromkeys(branch_ids))
        if not unique_ids:
            return {}
        statement = select(Branch).where(
            Branch.tenant_id == tenant_id,
            Branch.id.in_(unique_ids),
            Branch.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        return {row.id: row for row in result.scalars().all()}

    async def get_departments_by_ids(
        self,
        tenant_id: UUID,
        department_ids: Sequence[UUID],
    ) -> dict[UUID, Department]:
        unique_ids = list(dict.fromkeys(department_ids))
        if not unique_ids:
            return {}
        statement = select(Department).where(
            Department.tenant_id == tenant_id,
            Department.id.in_(unique_ids),
            Department.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        return {row.id: row for row in result.scalars().all()}

    async def get_employees_by_ids(
        self,
        tenant_id: UUID,
        employee_ids: Sequence[UUID],
    ) -> dict[UUID, Employee]:
        unique_ids = list(dict.fromkeys(employee_ids))
        if not unique_ids:
            return {}
        statement = select(Employee).where(
            Employee.tenant_id == tenant_id,
            Employee.id.in_(unique_ids),
            Employee.deleted_at.is_(None),
        )
        result = await self.session.execute(statement)
        return {row.id: row for row in result.scalars().all()}

    async def audit_employee_label(self, tenant_id: UUID, employee_id: UUID | None) -> str | None:
        if employee_id is None:
            return None
        employees = await self.get_employees_by_ids(tenant_id, [employee_id])
        employee = employees.get(employee_id)
        if employee is None:
            return None
        if employee.user_id is None:
            return employee.employee_code
        users = await self.get_users_by_ids(tenant_id, [employee.user_id])
        user = users.get(employee.user_id)
        if user is None:
            return employee.employee_code
        return f"{user.name} ({employee.employee_code})"

    async def get_users_by_ids(
        self,
        tenant_id: UUID,
        user_ids: Sequence[UUID],
    ) -> dict[UUID, User]:
        unique_ids = list(dict.fromkeys(user_ids))
        if not unique_ids:
            return {}
        statement = select(User).where(User.tenant_id == tenant_id, User.id.in_(unique_ids))
        result = await self.session.execute(statement)
        return {row.id: row for row in result.scalars().all()}

    async def count_employees_by_branch(
        self,
        tenant_id: UUID,
        branch_ids: Sequence[UUID],
    ) -> dict[UUID, int]:
        unique_ids = list(dict.fromkeys(branch_ids))
        if not unique_ids:
            return {}
        statement = (
            select(Employee.branch_id, func.count())
            .where(
                Employee.tenant_id == tenant_id,
                Employee.branch_id.in_(unique_ids),
                Employee.deleted_at.is_(None),
            )
            .group_by(Employee.branch_id)
        )
        result = await self.session.execute(statement)
        return {row.branch_id: int(row[1]) for row in result.all() if row.branch_id is not None}

    async def count_employees_by_department(
        self,
        tenant_id: UUID,
        department_ids: Sequence[UUID],
    ) -> dict[UUID, int]:
        unique_ids = list(dict.fromkeys(department_ids))
        if not unique_ids:
            return {}
        statement = (
            select(Employee.department_id, func.count())
            .where(
                Employee.tenant_id == tenant_id,
                Employee.department_id.in_(unique_ids),
                Employee.deleted_at.is_(None),
            )
            .group_by(Employee.department_id)
        )
        result = await self.session.execute(statement)
        return {
            row.department_id: int(row[1]) for row in result.all() if row.department_id is not None
        }

    async def count_departments_for_branch(self, tenant_id: UUID, branch_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(Department)
            .where(
                Department.tenant_id == tenant_id,
                Department.branch_id == branch_id,
                Department.deleted_at.is_(None),
            )
        )
        total = await self.session.scalar(statement)
        return int(total or 0)

    async def count_employees_for_branch(self, tenant_id: UUID, branch_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(Employee)
            .where(
                Employee.tenant_id == tenant_id,
                Employee.branch_id == branch_id,
                Employee.deleted_at.is_(None),
            )
        )
        total = await self.session.scalar(statement)
        return int(total or 0)

    async def count_employees_for_department(self, tenant_id: UUID, department_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(Employee)
            .where(
                Employee.tenant_id == tenant_id,
                Employee.department_id == department_id,
                Employee.deleted_at.is_(None),
            )
        )
        total = await self.session.scalar(statement)
        return int(total or 0)

    async def count_users(self, tenant_id: UUID) -> int:
        statement = select(func.count()).select_from(User).where(User.tenant_id == tenant_id)
        total = await self.session.scalar(statement)
        return int(total or 0)

    async def count_branches(self, tenant_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(Branch)
            .where(Branch.tenant_id == tenant_id, Branch.deleted_at.is_(None))
        )
        total = await self.session.scalar(statement)
        return int(total or 0)

    async def count_departments(self, tenant_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(Department)
            .where(Department.tenant_id == tenant_id, Department.deleted_at.is_(None))
        )
        total = await self.session.scalar(statement)
        return int(total or 0)
