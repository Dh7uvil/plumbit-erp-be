"""Business logic for authentication and access management."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.catalog import IDENTITY_MODULE, SYSTEM_ADMIN_ROLE_NAME, seed_tenant_permissions
from app.auth.models import Employee, Permission, Role, User
from app.auth.org_repository import OrganizationRepository
from app.auth.repository import AccessRepository
from app.auth.schemas import (
    AssignRolesRequest,
    BranchSummary,
    ChangePasswordRequest,
    DepartmentSummary,
    EmployeeSummary,
    EmployeeUpsert,
    LoginRequest,
    MeResponse,
    PermissionMatrixAction,
    PermissionMatrixModule,
    PermissionMatrixResource,
    PermissionMatrixResponse,
    PermissionResponse,
    RoleCreate,
    RoleDetailResponse,
    RoleResponse,
    RoleSummary,
    RoleUpdate,
    SetRolePermissionsRequest,
    TenantPublicResponse,
    TokenPairResponse,
    UserCreate,
    UserDetailResponse,
    UserFilter,
    UserResponse,
    UserUpdate,
)
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.services.audit import AuditWriter, audit_field_changes
from app.common.utils.datetime import utcnow
from app.core.config import get_settings
from app.core.enums import AuditAction, AuditStatus, EmployeeStatus, TenantStatus, UserStatus
from app.core.exceptions import (
    DuplicateResourceError,
    InvalidCredentialsError,
    InvalidStatusTransitionError,
    InvalidTokenError,
    ResourceNotFoundError,
    TokenExpiredError,
    ValidationError,
)
from app.core.permissions import build_permission
from app.core.security import (
    PasswordTooLongError,
    TokenClaims,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.db.session import transaction
from app.integrations.storage.client import S3Storage, presign_logo_url

logger = logging.getLogger(__name__)


def _role_names(roles: Sequence[Role]) -> list[str]:
    return sorted(role.name for role in roles)


def _permission_codes(permissions: Sequence[Permission]) -> list[str]:
    return sorted(build_permission(item.module, item.resource, item.action) for item in permissions)


def _role_snapshot(role: Role) -> dict[str, object]:
    return {
        "name": role.name,
        "description": role.description,
        "is_system_role": role.is_system_role,
    }


class AuthService:
    """Authentication, session, and identity-management use cases."""

    def __init__(self, session: AsyncSession, storage: S3Storage | None = None) -> None:
        self.session = session
        self.storage = storage
        self.repo = AccessRepository(session)
        self.org = OrganizationRepository(session)
        self.audit = AuditWriter(session)

    async def list_active_tenants(self) -> list[TenantPublicResponse]:
        rows = await self.repo.list_active_tenants()
        tenants: list[TenantPublicResponse] = []
        for tenant_id, name, logo_storage_key in rows:
            tenants.append(
                TenantPublicResponse(
                    tenant_id=tenant_id,
                    name=name,
                    logo_url=await presign_logo_url(self.storage, logo_storage_key),
                )
            )
        return tenants

    async def login(self, payload: LoginRequest) -> TokenPairResponse:
        failed_user_id: UUID | None = None
        tenant_exists = False
        try:
            async with transaction(self.session):
                tenant = await self.repo.get_tenant(payload.tenant_id)
                tenant_exists = tenant is not None
                user = (
                    await self.repo.get_user_by_email(payload.tenant_id, payload.email)
                    if tenant is not None and tenant.status == TenantStatus.ACTIVE
                    else None
                )
                password_hash = user.password_hash if user is not None else None
                credentials_ok = (
                    user is not None
                    and user.status == UserStatus.ACTIVE
                    and password_hash is not None
                    and verify_password(payload.password, password_hash)
                )
                if not credentials_ok or user is None:
                    failed_user_id = user.id if user is not None else None
                    logger.warning("login_failed", extra={"tenant_id": str(payload.tenant_id)})
                    raise InvalidCredentialsError()

                user.last_login_at = utcnow()
                tokens = await self._issue_token_pair(user)
                await self.audit.write(
                    tenant_id=user.tenant_id,
                    user_id=user.id,
                    action=AuditAction.LOGIN,
                    module=IDENTITY_MODULE,
                    entity_type="user",
                    entity_id=user.id,
                    status=AuditStatus.SUCCESS,
                )
                logger.info(
                    "user_logged_in",
                    extra={"user_id": str(user.id), "tenant_id": str(user.tenant_id)},
                )
                return tokens
        except InvalidCredentialsError:
            if tenant_exists:
                async with transaction(self.session):
                    await self.audit.write(
                        tenant_id=payload.tenant_id,
                        user_id=failed_user_id,
                        action=AuditAction.LOGIN,
                        module=IDENTITY_MODULE,
                        entity_type="user",
                        entity_id=failed_user_id,
                        status=AuditStatus.FAILED,
                    )
            raise

    async def refresh(self, refresh_token: str) -> TokenPairResponse:
        claims = self._decode_refresh(refresh_token)
        if claims.expires_at <= utcnow():
            raise TokenExpiredError()

        async with transaction(self.session):
            stored = await self.repo.get_refresh_token_by_jti(claims.token_id, for_update=True)
            if (
                stored is None
                or stored.revoked_at is not None
                or stored.expires_at <= utcnow()
                or str(stored.user_id) != claims.subject
            ):
                raise InvalidTokenError()
            if claims.tenant_id is not None and str(stored.tenant_id) != claims.tenant_id:
                raise InvalidTokenError()

            user = await self.repo.get_user(stored.tenant_id, stored.user_id)
            tenant = await self.repo.get_tenant(stored.tenant_id)
            if (
                user is None
                or user.status != UserStatus.ACTIVE
                or tenant is None
                or tenant.status != TenantStatus.ACTIVE
            ):
                raise InvalidCredentialsError()

            await self.repo.revoke_refresh_token(stored)
            return await self._issue_token_pair(user)

    async def logout(self, *, tenant_id: UUID, user_id: UUID, refresh_token: str) -> None:
        claims = self._decode_refresh(refresh_token)
        async with transaction(self.session):
            stored = await self.repo.get_refresh_token_by_jti(claims.token_id, for_update=True)
            if stored is None:
                return
            if stored.tenant_id != tenant_id or stored.user_id != user_id:
                raise InvalidTokenError()
            await self.repo.revoke_refresh_token(stored)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=user_id,
                action=AuditAction.LOGOUT,
                module=IDENTITY_MODULE,
                entity_type="user",
                entity_id=user_id,
            )

    async def me(self, *, tenant_id: UUID, user_id: UUID) -> MeResponse:
        user = await self._require_user(tenant_id, user_id)
        detail = await self._user_detail(tenant_id, user)
        permissions = await self.repo.list_user_permission_strings(tenant_id, user_id)
        return MeResponse(**detail.model_dump(), permissions=sorted(permissions))

    async def change_password(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        payload: ChangePasswordRequest,
    ) -> TokenPairResponse:
        new_hash = self._hash_password(payload.new_password)
        async with transaction(self.session):
            user = await self._require_user(tenant_id, user_id)
            if user.password_hash is None or not verify_password(
                payload.current_password,
                user.password_hash,
            ):
                raise InvalidCredentialsError()
            user.password_hash = new_hash
            await self.repo.revoke_user_refresh_tokens(tenant_id, user_id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="user",
                entity_id=user.id,
                new_values={"password_changed": True},
            )
            return await self._issue_token_pair(user)

    async def list_users(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        user_filter: UserFilter,
    ) -> tuple[list[UserResponse], int]:
        status = user_filter.status.value if user_filter.status is not None else None
        filters = {"status": status} if status is not None else None
        users, total = await self.repo.list_users(
            tenant_id,
            page=page,
            common_filter=user_filter,
            filters=filters,
            user_filter=user_filter,
        )
        user_list = list(users)
        roles_by_user = await self.repo.list_roles_for_users(
            tenant_id,
            [user.id for user in user_list],
        )
        employees_by_id = await self.org.get_employees_by_ids(
            tenant_id,
            [user.employee_id for user in user_list if user.employee_id is not None],
        )
        employee_summaries = await self._employee_summaries(
            tenant_id,
            list(employees_by_id.values()),
        )
        responses: list[UserResponse] = []
        for user in user_list:
            employee = (
                employee_summaries.get(user.employee_id) if user.employee_id is not None else None
            )
            responses.append(
                self._to_user_response(
                    user,
                    roles=roles_by_user.get(user.id, []),
                    employee=employee,
                )
            )
        return responses, total

    async def create_user(
        self,
        tenant_id: UUID,
        payload: UserCreate,
        *,
        actor_user_id: UUID,
    ) -> UserDetailResponse:
        password_hash = self._hash_password(payload.password)
        async with transaction(self.session):
            try:
                user = await self.repo.create_user(
                    tenant_id,
                    {
                        "name": payload.name,
                        "email": payload.email,
                        "password_hash": password_hash,
                        "phone": payload.phone,
                        "status": payload.status.value,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("A user with this email already exists") from exc
            await self._replace_user_roles(tenant_id, user.id, payload.role_ids)
            if payload.employee is not None:
                await self._upsert_employee(tenant_id, user, payload.employee)
            roles = await self.repo.list_user_roles(tenant_id, user.id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=IDENTITY_MODULE,
                entity_type="user",
                entity_id=user.id,
                new_values=await self._user_snapshot(tenant_id, user, roles=roles),
            )
            return await self._user_detail(tenant_id, user)

    async def get_user(self, tenant_id: UUID, user_id: UUID) -> UserDetailResponse:
        user = await self._require_user(tenant_id, user_id)
        return await self._user_detail(tenant_id, user)

    async def update_user(
        self,
        tenant_id: UUID,
        user_id: UUID,
        payload: UserUpdate,
        *,
        actor_user_id: UUID,
    ) -> UserDetailResponse:
        values = payload.model_dump(exclude_unset=True)
        employee_payload = values.pop("employee", None)
        status = values.get("status")
        if status == UserStatus.DISABLED and user_id == actor_user_id:
            raise ValidationError("You cannot deactivate your own account")
        if status is not None:
            values["status"] = str(status)

        async with transaction(self.session):
            user = await self._require_user(tenant_id, user_id)
            old_values = await self._user_snapshot(tenant_id, user)
            for name, value in values.items():
                setattr(user, name, value)
            try:
                await self.session.flush()
            except IntegrityError as exc:
                raise DuplicateResourceError("A user with this email already exists") from exc
            if employee_payload is not None:
                await self._upsert_employee(
                    tenant_id,
                    user,
                    EmployeeUpsert.model_validate(employee_payload),
                )
            new_values = await self._user_snapshot(tenant_id, user)
            if audit_field_changes(old_values, new_values):
                await self.audit.write(
                    tenant_id=tenant_id,
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=IDENTITY_MODULE,
                    entity_type="user",
                    entity_id=user.id,
                    old_values=old_values,
                    new_values=new_values,
                )
            return await self._user_detail(tenant_id, user)

    async def deactivate_user(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> UserDetailResponse:
        if user_id == actor_user_id:
            raise ValidationError("You cannot deactivate your own account")
        async with transaction(self.session):
            user = await self._require_user(tenant_id, user_id)
            old_status = user.status
            user.status = UserStatus.DISABLED
            await self.repo.revoke_user_refresh_tokens(tenant_id, user_id)
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="user",
                entity_id=user.id,
                old_values={"status": old_status},
                new_values={"status": user.status},
            )
            return await self._user_detail(tenant_id, user)

    async def activate_user(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> UserDetailResponse:
        async with transaction(self.session):
            user = await self._require_user(tenant_id, user_id)
            if user.status != UserStatus.DISABLED:
                raise InvalidStatusTransitionError("Only disabled users can be activated")
            old_status = user.status
            user.status = UserStatus.ACTIVE
            await self.session.flush()
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="user",
                entity_id=user.id,
                old_values={"status": old_status},
                new_values={"status": user.status},
            )
            return await self._user_detail(tenant_id, user)

    async def assign_roles(
        self,
        tenant_id: UUID,
        user_id: UUID,
        payload: AssignRolesRequest,
        *,
        actor_user_id: UUID,
    ) -> UserDetailResponse:
        async with transaction(self.session):
            user = await self._require_user(tenant_id, user_id)
            old_roles = await self.repo.list_user_roles(tenant_id, user.id)
            await self._replace_user_roles(tenant_id, user.id, payload.role_ids)
            new_roles = await self.repo.list_user_roles(tenant_id, user.id)
            old_values: dict[str, object] = {"roles": _role_names(old_roles)}
            new_values: dict[str, object] = {"roles": _role_names(new_roles)}
            if audit_field_changes(old_values, new_values):
                await self.audit.write(
                    tenant_id=tenant_id,
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=IDENTITY_MODULE,
                    entity_type="user",
                    entity_id=user.id,
                    old_values=old_values,
                    new_values=new_values,
                )
            return await self._user_detail(tenant_id, user)

    async def list_roles(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
    ) -> tuple[list[RoleResponse], int]:
        roles, total = await self.repo.list_roles(
            tenant_id,
            page=page,
            common_filter=common_filter,
        )
        role_list = list(roles)
        counts = await self.repo.count_users_by_role_ids(tenant_id, [role.id for role in role_list])
        return [
            RoleResponse.model_validate(role).model_copy(
                update={"user_count": counts.get(role.id, 0)}
            )
            for role in role_list
        ], total

    async def create_role(
        self,
        tenant_id: UUID,
        payload: RoleCreate,
        *,
        actor_user_id: UUID,
    ) -> RoleDetailResponse:
        async with transaction(self.session):
            try:
                role = await self.repo.create_role(
                    tenant_id,
                    {
                        "name": payload.name,
                        "description": payload.description,
                        "is_system_role": False,
                    },
                )
            except IntegrityError as exc:
                raise DuplicateResourceError("A role with this name already exists") from exc
            await self._replace_role_permissions(tenant_id, role.id, payload.permission_ids)
            permissions = await self.repo.list_role_permissions(tenant_id, role.id)
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.CREATE,
                module=IDENTITY_MODULE,
                entity_type="role",
                entity_id=role.id,
                new_values={**_role_snapshot(role), "permissions": _permission_codes(permissions)},
            )
            return await self._role_detail(tenant_id, role)

    async def get_role(self, tenant_id: UUID, role_id: UUID) -> RoleDetailResponse:
        role = await self._require_role(tenant_id, role_id)
        return await self._role_detail(tenant_id, role)

    async def update_role(
        self,
        tenant_id: UUID,
        role_id: UUID,
        payload: RoleUpdate,
        *,
        actor_user_id: UUID,
    ) -> RoleDetailResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            role = await self._require_role(tenant_id, role_id)
            if role.is_system_role and "name" in values and values["name"] != role.name:
                raise ValidationError("System role names cannot be changed")
            old_values = _role_snapshot(role)
            for name, value in values.items():
                setattr(role, name, value)
            try:
                await self.session.flush()
            except IntegrityError as exc:
                raise DuplicateResourceError("A role with this name already exists") from exc
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="role",
                entity_id=role.id,
                old_values=old_values,
                new_values=_role_snapshot(role),
            )
            return await self._role_detail(tenant_id, role)

    async def delete_role(
        self,
        tenant_id: UUID,
        role_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> RoleResponse:
        async with transaction(self.session):
            role = await self._require_role(tenant_id, role_id)
            if role.is_system_role:
                raise ValidationError("System roles cannot be deleted")
            counts = await self.repo.count_users_by_role_ids(tenant_id, [role.id])
            response = RoleResponse.model_validate(role).model_copy(
                update={"user_count": counts.get(role.id, 0)}
            )
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.DELETE,
                module=IDENTITY_MODULE,
                entity_type="role",
                entity_id=role.id,
                old_values=_role_snapshot(role),
            )
            await self.repo.delete_role(role)
        return response

    async def set_role_permissions(
        self,
        tenant_id: UUID,
        role_id: UUID,
        payload: SetRolePermissionsRequest,
        *,
        actor_user_id: UUID,
    ) -> RoleDetailResponse:
        async with transaction(self.session):
            role = await self._require_role(tenant_id, role_id)
            old_permissions = await self.repo.list_role_permissions(tenant_id, role.id)
            await self._replace_role_permissions(tenant_id, role.id, payload.permission_ids)
            new_permissions = await self.repo.list_role_permissions(tenant_id, role.id)
            old_values: dict[str, object] = {"permissions": _permission_codes(old_permissions)}
            new_values: dict[str, object] = {"permissions": _permission_codes(new_permissions)}
            if audit_field_changes(old_values, new_values):
                await self.audit.write(
                    tenant_id=tenant_id,
                    user_id=actor_user_id,
                    action=AuditAction.UPDATE,
                    module=IDENTITY_MODULE,
                    entity_type="role",
                    entity_id=role.id,
                    old_values=old_values,
                    new_values=new_values,
                )
            return await self._role_detail(tenant_id, role)

    async def reset_role_permissions(
        self,
        tenant_id: UUID,
        role_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> RoleDetailResponse:
        async with transaction(self.session):
            role = await self._require_role(tenant_id, role_id)
            if not role.is_system_role or role.name != SYSTEM_ADMIN_ROLE_NAME:
                raise ValidationError("Only the system Superadmin role can be reset to the catalog")
            permissions = await seed_tenant_permissions(self.session, tenant_id)
            await self.repo.replace_role_permissions(
                tenant_id,
                role.id,
                [permission.id for permission in permissions],
            )
            await self.audit.write(
                tenant_id=tenant_id,
                user_id=actor_user_id,
                action=AuditAction.UPDATE,
                module=IDENTITY_MODULE,
                entity_type="role",
                entity_id=role.id,
                new_values={"permissions_reset": True},
            )
            return await self._role_detail(tenant_id, role)

    async def list_permissions(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        module: str | None = None,
    ) -> tuple[list[PermissionResponse], int]:
        filters = {"module": module} if module is not None else None
        permissions, total = await self.repo.list_permissions(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
        )
        return [PermissionResponse.model_validate(item) for item in permissions], total

    async def permission_matrix(
        self,
        tenant_id: UUID,
        *,
        role_id: UUID | None = None,
    ) -> PermissionMatrixResponse:
        granted_ids: set[UUID] = set()
        if role_id is not None:
            role = await self._require_role(tenant_id, role_id)
            granted = await self.repo.list_role_permissions(tenant_id, role.id)
            granted_ids = {item.id for item in granted}

        catalog = await self.repo.list_all_permissions(tenant_id)
        modules: dict[str, dict[str, list[PermissionMatrixAction]]] = {}
        for item in catalog:
            code = build_permission(item.module, item.resource, item.action)
            modules.setdefault(item.module, {}).setdefault(item.resource, []).append(
                PermissionMatrixAction(
                    id=item.id,
                    action=item.action,
                    code=code,
                    granted=item.id in granted_ids,
                )
            )
        return PermissionMatrixResponse(
            modules=[
                PermissionMatrixModule(
                    module=module_name,
                    resources=[
                        PermissionMatrixResource(resource=resource_name, actions=actions)
                        for resource_name, actions in resources.items()
                    ],
                )
                for module_name, resources in modules.items()
            ]
        )

    async def _user_snapshot(
        self, tenant_id: UUID, user: User, *, roles: Sequence[Role] | None = None
    ) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "name": user.name,
            "email": user.email,
            "phone": user.phone,
            "status": user.status,
            **(await self._employee_audit_values(tenant_id, user.employee_id)),
        }
        if roles is not None:
            snapshot["roles"] = _role_names(roles)
        return snapshot

    async def _employee_audit_values(
        self, tenant_id: UUID, employee_id: UUID | None
    ) -> dict[str, object]:
        empty: dict[str, object] = {
            "employee": None,
            "designation": None,
            "branch": None,
            "department": None,
            "joining_date": None,
        }
        if employee_id is None:
            return empty
        employees = await self.org.get_employees_by_ids(tenant_id, [employee_id])
        employee = employees.get(employee_id)
        if employee is None:
            return empty
        branch_name: str | None = None
        if employee.branch_id is not None:
            branches = await self.org.get_branches_by_ids(tenant_id, [employee.branch_id])
            branch = branches.get(employee.branch_id)
            if branch is not None:
                branch_name = branch.name
        department_name: str | None = None
        if employee.department_id is not None:
            departments = await self.org.get_departments_by_ids(tenant_id, [employee.department_id])
            department = departments.get(employee.department_id)
            if department is not None:
                department_name = department.name
        return {
            "employee": employee.employee_code,
            "designation": employee.designation,
            "branch": branch_name,
            "department": department_name,
            "joining_date": employee.joining_date,
        }

    async def _require_user(self, tenant_id: UUID, user_id: UUID) -> User:
        user = await self.repo.get_user(tenant_id, user_id)
        if user is None:
            raise ResourceNotFoundError("User not found")
        return user

    async def _require_role(self, tenant_id: UUID, role_id: UUID) -> Role:
        role = await self.repo.get_role(tenant_id, role_id)
        if role is None:
            raise ResourceNotFoundError("Role not found")
        return role

    async def _user_detail(self, tenant_id: UUID, user: User) -> UserDetailResponse:
        await self.session.refresh(user)
        roles = await self.repo.list_user_roles(tenant_id, user.id)
        employee = None
        if user.employee_id is not None:
            employees = await self.org.get_employees_by_ids(tenant_id, [user.employee_id])
            summaries = await self._employee_summaries(tenant_id, list(employees.values()))
            employee = summaries.get(user.employee_id)
        return UserDetailResponse.model_validate(
            self._to_user_response(user, roles=list(roles), employee=employee)
        )

    def _to_user_response(
        self,
        user: User,
        *,
        roles: Sequence[Role],
        employee: EmployeeSummary | None,
    ) -> UserResponse:
        return UserResponse.model_validate(user).model_copy(
            update={
                "roles": [RoleSummary.model_validate(role) for role in roles],
                "employee": employee,
            }
        )

    async def _employee_summaries(
        self,
        tenant_id: UUID,
        employees: Sequence[Employee],
    ) -> dict[UUID, EmployeeSummary]:
        branch_ids = [item.branch_id for item in employees if item.branch_id is not None]
        department_ids = [
            item.department_id for item in employees if item.department_id is not None
        ]
        branches = await self.org.get_branches_by_ids(tenant_id, branch_ids)
        departments = await self.org.get_departments_by_ids(tenant_id, department_ids)
        summaries: dict[UUID, EmployeeSummary] = {}
        for employee in employees:
            summaries[employee.id] = EmployeeSummary(
                id=employee.id,
                employee_code=employee.employee_code,
                designation=employee.designation,
                joining_date=employee.joining_date,
                status=EmployeeStatus(employee.status),
                branch=BranchSummary.model_validate(branches[employee.branch_id])
                if employee.branch_id is not None and employee.branch_id in branches
                else None,
                department=DepartmentSummary.model_validate(departments[employee.department_id])
                if employee.department_id is not None and employee.department_id in departments
                else None,
            )
        return summaries

    async def _upsert_employee(
        self,
        tenant_id: UUID,
        user: User,
        payload: EmployeeUpsert,
    ) -> Employee:
        branch_id = payload.branch_id
        department_id = payload.department_id
        if branch_id is not None:
            branch = await self.org.get_branch(tenant_id, branch_id)
            if branch is None:
                raise ResourceNotFoundError("Branch not found")
        if department_id is not None:
            department = await self.org.get_department(tenant_id, department_id)
            if department is None:
                raise ResourceNotFoundError("Department not found")
            if branch_id is None:
                branch_id = department.branch_id
            elif department.branch_id != branch_id:
                raise ValidationError("Department does not belong to the selected branch")

        values: dict[str, object] = {
            "branch_id": branch_id,
            "department_id": department_id,
            "designation": payload.designation,
            "joining_date": payload.joining_date,
            "user_id": user.id,
        }
        try:
            if user.employee_id is None:
                values["employee_code"] = await self.org.next_employee_code(tenant_id)
                values["status"] = EmployeeStatus.ACTIVE.value
                employee = await self.org.create_employee(tenant_id, values)
                user.employee_id = employee.id
                await self.session.flush()
                return employee
            updated = await self.org.update_employee(tenant_id, user.employee_id, values)
            if updated is None:
                values["employee_code"] = await self.org.next_employee_code(tenant_id)
                values["status"] = EmployeeStatus.ACTIVE.value
                created = await self.org.create_employee(tenant_id, values)
                user.employee_id = created.id
                await self.session.flush()
                return created
            return updated
        except IntegrityError as exc:
            raise DuplicateResourceError("An employee with this code already exists") from exc

    async def _role_detail(self, tenant_id: UUID, role: Role) -> RoleDetailResponse:
        await self.session.refresh(role)
        permissions = await self.repo.list_role_permissions(tenant_id, role.id)
        counts = await self.repo.count_users_by_role_ids(tenant_id, [role.id])
        return RoleDetailResponse(
            **RoleResponse.model_validate(role)
            .model_copy(update={"user_count": counts.get(role.id, 0)})
            .model_dump(),
            permissions=[PermissionResponse.model_validate(item) for item in permissions],
        )

    async def _replace_user_roles(
        self,
        tenant_id: UUID,
        user_id: UUID,
        role_ids: Sequence[UUID],
    ) -> None:
        unique_ids = list(dict.fromkeys(role_ids))
        roles = await self.repo.get_roles_by_ids(tenant_id, unique_ids)
        if len(roles) != len(unique_ids):
            raise ResourceNotFoundError("Role not found")
        await self.repo.replace_user_roles(tenant_id, user_id, unique_ids)

    async def _replace_role_permissions(
        self,
        tenant_id: UUID,
        role_id: UUID,
        permission_ids: Sequence[UUID],
    ) -> None:
        unique_ids = list(dict.fromkeys(permission_ids))
        permissions = await self.repo.get_permissions_by_ids(tenant_id, unique_ids)
        if len(permissions) != len(unique_ids):
            raise ResourceNotFoundError("Permission not found")
        await self.repo.replace_role_permissions(tenant_id, role_id, unique_ids)

    def _decode_refresh(self, refresh_token: str) -> TokenClaims:
        settings = get_settings()
        return decode_refresh_token(
            refresh_token,
            secret=settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )

    def _hash_password(self, password: str) -> str:
        try:
            return hash_password(password)
        except PasswordTooLongError as exc:
            raise ValidationError("Password exceeds bcrypt's 72-byte UTF-8 limit") from exc

    async def _issue_token_pair(self, user: User) -> TokenPairResponse:
        settings = get_settings()
        secret = settings.jwt_secret.get_secret_value()
        algorithm = settings.jwt_algorithm
        access_delta = timedelta(minutes=settings.jwt_access_token_ttl_minutes)
        refresh_delta = timedelta(minutes=settings.jwt_refresh_token_ttl_minutes)
        tenant_id = str(user.tenant_id)
        subject = str(user.id)

        access_token = create_access_token(
            subject=subject,
            secret=secret,
            expires_delta=access_delta,
            tenant_id=tenant_id,
            algorithm=algorithm,
        )
        refresh_token = create_refresh_token(
            subject=subject,
            secret=secret,
            expires_delta=refresh_delta,
            tenant_id=tenant_id,
            algorithm=algorithm,
        )
        refresh_claims = decode_refresh_token(
            refresh_token,
            secret=secret,
            algorithm=algorithm,
        )
        await self.repo.create_refresh_token(
            tenant_id=user.tenant_id,
            user_id=user.id,
            jti=refresh_claims.token_id,
            expires_at=refresh_claims.expires_at,
        )
        return TokenPairResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=int(access_delta.total_seconds()),
        )
