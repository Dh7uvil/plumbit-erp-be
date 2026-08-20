"""Business logic for authentication and access management."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User
from app.auth.repository import AccessRepository
from app.auth.schemas import (
    AssignRolesRequest,
    ChangePasswordRequest,
    LoginRequest,
    MeResponse,
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
    UserResponse,
    UserUpdate,
)
from app.common.schemas.filters import BaseFilter
from app.common.schemas.pagination import PageParams
from app.common.utils.datetime import utcnow
from app.core.config import get_settings
from app.core.enums import TenantStatus, UserStatus
from app.core.exceptions import (
    DuplicateResourceError,
    InvalidCredentialsError,
    InvalidTokenError,
    ResourceNotFoundError,
    TokenExpiredError,
    ValidationError,
)
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

logger = logging.getLogger(__name__)


class AuthService:
    """Authentication, session, and identity-management use cases."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AccessRepository(session)

    async def list_active_tenants(self) -> list[TenantPublicResponse]:
        rows = await self.repo.list_active_tenants()
        return [TenantPublicResponse(tenant_id=tenant_id, name=name) for tenant_id, name in rows]

    async def login(self, payload: LoginRequest) -> TokenPairResponse:
        async with transaction(self.session):
            tenant = await self.repo.get_tenant(payload.tenant_id)
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
                logger.warning("login_failed", extra={"tenant_id": str(payload.tenant_id)})
                raise InvalidCredentialsError()

            user.last_login_at = utcnow()
            tokens = await self._issue_token_pair(user)

        logger.info(
            "user_logged_in",
            extra={"user_id": str(user.id), "tenant_id": str(user.tenant_id)},
        )
        return tokens

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

    async def me(self, *, tenant_id: UUID, user_id: UUID) -> MeResponse:
        user = await self._require_user(tenant_id, user_id)
        roles = await self.repo.list_user_roles(tenant_id, user_id)
        permissions = await self.repo.list_user_permission_strings(tenant_id, user_id)
        return MeResponse(
            **UserResponse.model_validate(user).model_dump(),
            roles=[RoleSummary.model_validate(role) for role in roles],
            permissions=sorted(permissions),
        )

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
            return await self._issue_token_pair(user)

    async def list_users(
        self,
        tenant_id: UUID,
        *,
        page: PageParams,
        common_filter: BaseFilter | None = None,
        status: str | None = None,
    ) -> tuple[list[UserResponse], int]:
        filters = {"status": status} if status is not None else None
        users, total = await self.repo.list_users(
            tenant_id,
            page=page,
            common_filter=common_filter,
            filters=filters,
        )
        return [UserResponse.model_validate(user) for user in users], total

    async def create_user(self, tenant_id: UUID, payload: UserCreate) -> UserDetailResponse:
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
        status = values.get("status")
        if status == UserStatus.DISABLED and user_id == actor_user_id:
            raise ValidationError("You cannot deactivate your own account")
        if status is not None:
            values["status"] = str(status)

        async with transaction(self.session):
            user = await self._require_user(tenant_id, user_id)
            for name, value in values.items():
                setattr(user, name, value)
            try:
                await self.session.flush()
            except IntegrityError as exc:
                raise DuplicateResourceError("A user with this email already exists") from exc
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
            user.status = UserStatus.DISABLED
            await self.repo.revoke_user_refresh_tokens(tenant_id, user_id)
            await self.session.flush()
            return await self._user_detail(tenant_id, user)

    async def assign_roles(
        self,
        tenant_id: UUID,
        user_id: UUID,
        payload: AssignRolesRequest,
    ) -> UserDetailResponse:
        async with transaction(self.session):
            user = await self._require_user(tenant_id, user_id)
            await self._replace_user_roles(tenant_id, user.id, payload.role_ids)
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
        return [RoleResponse.model_validate(role) for role in roles], total

    async def create_role(self, tenant_id: UUID, payload: RoleCreate) -> RoleDetailResponse:
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
            return await self._role_detail(tenant_id, role)

    async def get_role(self, tenant_id: UUID, role_id: UUID) -> RoleDetailResponse:
        role = await self._require_role(tenant_id, role_id)
        return await self._role_detail(tenant_id, role)

    async def update_role(
        self,
        tenant_id: UUID,
        role_id: UUID,
        payload: RoleUpdate,
    ) -> RoleDetailResponse:
        values = payload.model_dump(exclude_unset=True)
        async with transaction(self.session):
            role = await self._require_role(tenant_id, role_id)
            if role.is_system_role and "name" in values and values["name"] != role.name:
                raise ValidationError("System role names cannot be changed")
            for name, value in values.items():
                setattr(role, name, value)
            try:
                await self.session.flush()
            except IntegrityError as exc:
                raise DuplicateResourceError("A role with this name already exists") from exc
            return await self._role_detail(tenant_id, role)

    async def delete_role(self, tenant_id: UUID, role_id: UUID) -> RoleResponse:
        async with transaction(self.session):
            role = await self._require_role(tenant_id, role_id)
            if role.is_system_role:
                raise ValidationError("System roles cannot be deleted")
            response = RoleResponse.model_validate(role)
            await self.repo.delete_role(role)
        return response

    async def set_role_permissions(
        self,
        tenant_id: UUID,
        role_id: UUID,
        payload: SetRolePermissionsRequest,
    ) -> RoleDetailResponse:
        async with transaction(self.session):
            role = await self._require_role(tenant_id, role_id)
            await self._replace_role_permissions(tenant_id, role.id, payload.permission_ids)
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
        roles = await self.repo.list_user_roles(tenant_id, user.id)
        return UserDetailResponse(
            **UserResponse.model_validate(user).model_dump(),
            roles=[RoleSummary.model_validate(role) for role in roles],
        )

    async def _role_detail(self, tenant_id: UUID, role: Role) -> RoleDetailResponse:
        permissions = await self.repo.list_role_permissions(tenant_id, role.id)
        return RoleDetailResponse(
            **RoleResponse.model_validate(role).model_dump(),
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
