"""Database access for tenants, users, roles, permissions, and refresh tokens."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.auth.models import (
    Department,
    Employee,
    Permission,
    RefreshToken,
    Role,
    RolePermission,
    Tenant,
    User,
    UserRole,
)
from app.auth.schemas import UserFilter
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.utils.datetime import utcnow
from app.core.enums import TenantStatus
from app.core.permissions import build_permission
from app.db.base import Base


class AccessRepository:
    """Queries for the access-management slice."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _column(model: type[Base], name: str) -> InstrumentedAttribute[Any]:
        column = getattr(model, name, None)
        if not isinstance(column, InstrumentedAttribute):
            msg = f"{model.__name__} has no mapped column {name!r}"
            raise TypeError(msg)
        return column

    def _list_criteria(
        self,
        model: type[Base],
        tenant_id: UUID,
        *,
        filters: Mapping[str, object] | None = None,
        common_filter: BaseFilter | None = None,
        search_fields: frozenset[str] = frozenset(),
        allowed_filter_fields: frozenset[str] = frozenset(),
        extra_criteria: Sequence[ColumnElement[bool]] = (),
    ) -> list[ColumnElement[bool]]:
        criteria: list[ColumnElement[bool]] = [self._column(model, "tenant_id") == tenant_id]

        if filters:
            unknown = filters.keys() - allowed_filter_fields
            if unknown:
                fields = ", ".join(sorted(unknown))
                msg = f"filter fields are not allowed: {fields}"
                raise ValueError(msg)
            criteria.extend(self._column(model, name) == value for name, value in filters.items())

        if common_filter is not None:
            if common_filter.date_from is not None:
                criteria.append(self._column(model, "created_at") >= common_filter.date_from)
            if common_filter.date_to is not None:
                criteria.append(self._column(model, "created_at") <= common_filter.date_to)
            if common_filter.search is not None:
                if not search_fields:
                    msg = "search is not supported by this repository"
                    raise ValueError(msg)
                search_term = f"%{common_filter.search}%"
                criteria.append(
                    or_(*(self._column(model, field).ilike(search_term) for field in search_fields))
                )

        criteria.extend(extra_criteria)
        return criteria

    def _apply_sort(
        self,
        model: type[Base],
        statement: Select[tuple[Any]],
        *,
        common_filter: BaseFilter | None,
        allowed_sort_fields: frozenset[str],
    ) -> Select[tuple[Any]]:
        sort_by = common_filter.sort_by if common_filter else "created_at"
        sort_order = common_filter.sort_order if common_filter else "desc"
        if sort_by not in allowed_sort_fields:
            msg = f"sort field is not allowed: {sort_by}"
            raise ValueError(msg)
        sort_column = self._column(model, sort_by)
        ordering = sort_column.desc() if sort_order == "desc" else sort_column.asc()
        return statement.order_by(ordering)

    async def _paginated[ModelT: Base](
        self,
        model: type[ModelT],
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None,
        filters: Mapping[str, object] | None,
        search_fields: frozenset[str],
        allowed_filter_fields: frozenset[str],
        allowed_sort_fields: frozenset[str],
        extra_criteria: Sequence[ColumnElement[bool]] = (),
    ) -> tuple[Sequence[ModelT], int]:
        criteria = self._list_criteria(
            model,
            tenant_id,
            filters=filters,
            common_filter=common_filter,
            search_fields=search_fields,
            allowed_filter_fields=allowed_filter_fields,
            extra_criteria=extra_criteria,
        )
        statement = self._apply_sort(
            model,
            select(model).where(*criteria),
            common_filter=common_filter,
            allowed_sort_fields=allowed_sort_fields,
        )
        statement = statement.offset(page.offset).limit(page.page_size)
        count_statement = select(func.count()).select_from(model).where(*criteria)

        result = await self.session.execute(statement)
        total = await self.session.scalar(count_statement)
        return result.scalars().all(), int(total or 0)

    async def list_active_tenants(self) -> list[tuple[UUID, str, str | None]]:
        """Return ``(id, name, logo_storage_key)`` for active tenants only."""

        statement = (
            select(Tenant.id, Tenant.name, Tenant.logo_storage_key)
            .where(Tenant.status == TenantStatus.ACTIVE)
            .order_by(Tenant.name.asc())
        )
        result = await self.session.execute(statement)
        return [(row.id, row.name, row.logo_storage_key) for row in result.all()]

    async def get_tenant(self, tenant_id: UUID) -> Tenant | None:
        statement = select(Tenant).where(Tenant.id == tenant_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        statement = select(User).where(User.id == user_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_user(self, tenant_id: UUID, user_id: UUID) -> User | None:
        statement = select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_user_by_email(self, tenant_id: UUID, email: str) -> User | None:
        statement = select(User).where(User.tenant_id == tenant_id, User.email == email)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    def _user_list_extra_criteria(
        self,
        tenant_id: UUID,
        user_filter: UserFilter | None,
    ) -> list[ColumnElement[bool]]:
        if user_filter is None:
            return []

        extra_criteria: list[ColumnElement[bool]] = []
        role_ids = user_filter.collected_role_ids()
        if role_ids:
            extra_criteria.append(
                User.id.in_(
                    select(UserRole.user_id).where(
                        UserRole.tenant_id == tenant_id,
                        UserRole.role_id.in_(role_ids),
                    )
                )
            )
        if user_filter.phone is not None:
            extra_criteria.append(User.phone.ilike(f"%{user_filter.phone}%"))
        if user_filter.last_login_from is not None:
            extra_criteria.append(User.last_login_at >= user_filter.last_login_from)
        if user_filter.last_login_to is not None:
            extra_criteria.append(User.last_login_at <= user_filter.last_login_to)

        employee_match = self._employee_match_exists(tenant_id, user_filter)
        if employee_match is not None:
            extra_criteria.append(employee_match)
        return extra_criteria

    def _employee_match_exists(
        self,
        tenant_id: UUID,
        user_filter: UserFilter,
    ) -> ColumnElement[bool] | None:
        has_employee_filters = any(
            (
                user_filter.department_id is not None,
                user_filter.branch_id is not None,
                user_filter.designation is not None,
                user_filter.joining_date is not None,
                user_filter.joining_date_from is not None,
                user_filter.joining_date_to is not None,
                user_filter.employee_status is not None,
                user_filter.employee_code is not None,
                user_filter.manager_id is not None,
            )
        )
        if not has_employee_filters:
            return None

        criteria: list[ColumnElement[bool]] = [
            Employee.id == User.employee_id,
            Employee.tenant_id == tenant_id,
            Employee.deleted_at.is_(None),
        ]
        if user_filter.department_id is not None:
            criteria.append(Employee.department_id == user_filter.department_id)
        if user_filter.branch_id is not None:
            criteria.append(Employee.branch_id == user_filter.branch_id)
        if user_filter.designation is not None:
            criteria.append(Employee.designation.ilike(f"%{user_filter.designation}%"))
        if user_filter.joining_date is not None:
            criteria.append(Employee.joining_date == user_filter.joining_date)
        if user_filter.joining_date_from is not None:
            criteria.append(Employee.joining_date >= user_filter.joining_date_from)
        if user_filter.joining_date_to is not None:
            criteria.append(Employee.joining_date <= user_filter.joining_date_to)
        if user_filter.employee_status is not None:
            criteria.append(Employee.status == user_filter.employee_status.value)
        if user_filter.employee_code is not None:
            criteria.append(Employee.employee_code.ilike(f"%{user_filter.employee_code}%"))

        statement = select(Employee.id)
        if user_filter.manager_id is not None:
            statement = statement.join(
                Department,
                (Department.id == Employee.department_id)
                & (Department.tenant_id == tenant_id)
                & (Department.deleted_at.is_(None)),
            )
            criteria.append(Department.manager_id == user_filter.manager_id)
        return exists(statement.where(*criteria))

    async def list_users(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
        user_filter: UserFilter | None = None,
    ) -> tuple[Sequence[User], int]:
        items, total = await self._paginated(
            User,
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
            search_fields=frozenset({"name", "email"}),
            allowed_filter_fields=frozenset({"status"}),
            allowed_sort_fields=frozenset(
                {"created_at", "updated_at", "name", "email", "status", "last_login_at"}
            ),
            extra_criteria=self._user_list_extra_criteria(tenant_id, user_filter),
        )
        return items, total

    async def create_user(self, tenant_id: UUID, values: Mapping[str, object]) -> User:
        user = User(tenant_id=tenant_id)
        for name, value in values.items():
            setattr(user, name, value)
        self.session.add(user)
        await self.session.flush()
        return user

    async def list_user_permission_strings(
        self,
        tenant_id: UUID,
        user_id: UUID,
    ) -> frozenset[str]:
        statement = (
            select(Permission.module, Permission.resource, Permission.action)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(
                UserRole.user_id == user_id,
                UserRole.tenant_id == tenant_id,
                RolePermission.tenant_id == tenant_id,
                Permission.tenant_id == tenant_id,
            )
            .distinct()
        )
        result = await self.session.execute(statement)
        return frozenset(
            build_permission(row.module, row.resource, row.action) for row in result.all()
        )

    async def list_user_roles(self, tenant_id: UUID, user_id: UUID) -> Sequence[Role]:
        statement = (
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(
                UserRole.user_id == user_id,
                UserRole.tenant_id == tenant_id,
                Role.tenant_id == tenant_id,
            )
            .order_by(Role.name.asc())
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def get_roles_by_ids(
        self,
        tenant_id: UUID,
        role_ids: Sequence[UUID],
    ) -> Sequence[Role]:
        if not role_ids:
            return []
        statement = select(Role).where(Role.tenant_id == tenant_id, Role.id.in_(role_ids))
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def replace_user_roles(
        self,
        tenant_id: UUID,
        user_id: UUID,
        role_ids: Sequence[UUID],
    ) -> None:
        await self.session.execute(
            delete(UserRole).where(
                UserRole.tenant_id == tenant_id,
                UserRole.user_id == user_id,
            )
        )
        await self.session.flush()
        for role_id in role_ids:
            self.session.add(UserRole(tenant_id=tenant_id, user_id=user_id, role_id=role_id))
        await self.session.flush()

    async def get_role(self, tenant_id: UUID, role_id: UUID) -> Role | None:
        statement = select(Role).where(Role.id == role_id, Role.tenant_id == tenant_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_roles(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
    ) -> tuple[Sequence[Role], int]:
        items, total = await self._paginated(
            Role,
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=None,
            search_fields=frozenset({"name", "description"}),
            allowed_filter_fields=frozenset(),
            allowed_sort_fields=frozenset({"created_at", "updated_at", "name"}),
        )
        return items, total

    async def create_role(self, tenant_id: UUID, values: Mapping[str, object]) -> Role:
        role = Role(tenant_id=tenant_id)
        for name, value in values.items():
            setattr(role, name, value)
        self.session.add(role)
        await self.session.flush()
        return role

    async def delete_role(self, role: Role) -> None:
        await self.session.delete(role)
        await self.session.flush()

    async def get_permissions_by_ids(
        self,
        tenant_id: UUID,
        permission_ids: Sequence[UUID],
    ) -> Sequence[Permission]:
        if not permission_ids:
            return []
        statement = select(Permission).where(
            Permission.tenant_id == tenant_id,
            Permission.id.in_(permission_ids),
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def list_role_permissions(
        self,
        tenant_id: UUID,
        role_id: UUID,
    ) -> Sequence[Permission]:
        statement = (
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(
                RolePermission.role_id == role_id,
                RolePermission.tenant_id == tenant_id,
                Permission.tenant_id == tenant_id,
            )
            .order_by(Permission.module.asc(), Permission.resource.asc(), Permission.action.asc())
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def replace_role_permissions(
        self,
        tenant_id: UUID,
        role_id: UUID,
        permission_ids: Sequence[UUID],
    ) -> None:
        await self.session.execute(
            delete(RolePermission).where(
                RolePermission.tenant_id == tenant_id,
                RolePermission.role_id == role_id,
            )
        )
        await self.session.flush()
        for permission_id in permission_ids:
            self.session.add(
                RolePermission(
                    tenant_id=tenant_id,
                    role_id=role_id,
                    permission_id=permission_id,
                )
            )
        await self.session.flush()

    async def list_permissions(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> tuple[Sequence[Permission], int]:
        items, total = await self._paginated(
            Permission,
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
            search_fields=frozenset({"module", "resource", "action"}),
            allowed_filter_fields=frozenset({"module"}),
            allowed_sort_fields=frozenset({"created_at", "module", "resource", "action"}),
        )
        return items, total

    async def create_refresh_token(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        jti: str,
        expires_at: datetime,
    ) -> RefreshToken:
        token = RefreshToken(
            tenant_id=tenant_id,
            user_id=user_id,
            jti=jti,
            expires_at=expires_at,
        )
        self.session.add(token)
        await self.session.flush()
        return token

    async def get_refresh_token_by_jti(
        self,
        jti: str,
        *,
        for_update: bool = False,
    ) -> RefreshToken | None:
        statement = select(RefreshToken).where(RefreshToken.jti == jti)
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def revoke_refresh_token(self, token: RefreshToken) -> None:
        if token.revoked_at is None:
            token.revoked_at = utcnow()
            await self.session.flush()

    async def revoke_user_refresh_tokens(self, tenant_id: UUID, user_id: UUID) -> None:
        statement = select(RefreshToken).where(
            RefreshToken.tenant_id == tenant_id,
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        result = await self.session.execute(statement)
        revoked_at = utcnow()
        for token in result.scalars().all():
            token.revoked_at = revoked_at
        await self.session.flush()

    async def list_roles_for_users(
        self,
        tenant_id: UUID,
        user_ids: Sequence[UUID],
    ) -> dict[UUID, list[Role]]:
        unique_ids = list(dict.fromkeys(user_ids))
        if not unique_ids:
            return {}
        statement = (
            select(UserRole.user_id, Role)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                UserRole.tenant_id == tenant_id,
                Role.tenant_id == tenant_id,
                UserRole.user_id.in_(unique_ids),
            )
            .order_by(Role.name.asc())
        )
        result = await self.session.execute(statement)
        grouped: dict[UUID, list[Role]] = {user_id: [] for user_id in unique_ids}
        for user_id, role in result.all():
            grouped.setdefault(user_id, []).append(role)
        return grouped

    async def count_users_by_role_ids(
        self,
        tenant_id: UUID,
        role_ids: Sequence[UUID],
    ) -> dict[UUID, int]:
        unique_ids = list(dict.fromkeys(role_ids))
        if not unique_ids:
            return {}
        statement = (
            select(UserRole.role_id, func.count())
            .where(UserRole.tenant_id == tenant_id, UserRole.role_id.in_(unique_ids))
            .group_by(UserRole.role_id)
        )
        result = await self.session.execute(statement)
        return {row.role_id: int(row[1]) for row in result.all()}

    async def list_all_permissions(self, tenant_id: UUID) -> Sequence[Permission]:
        statement = (
            select(Permission)
            .where(Permission.tenant_id == tenant_id)
            .order_by(Permission.module.asc(), Permission.resource.asc(), Permission.action.asc())
        )
        result = await self.session.execute(statement)
        return result.scalars().all()
