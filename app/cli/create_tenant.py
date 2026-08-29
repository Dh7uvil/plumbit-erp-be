"""Interactive CLI to provision a tenant with an admin user."""

from __future__ import annotations

import asyncio
import re
import secrets
import sys
from dataclasses import dataclass
from getpass import getpass
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.auth.catalog import SYSTEM_ADMIN_ROLE_NAME, grant_catalog_to_role
from app.auth.models import Role, Tenant, User, UserRole
from app.common.utils.validators import normalize_required_text
from app.core.enums import TenantStatus, UserStatus
from app.core.exceptions import DuplicateResourceError, ValidationError
from app.core.security import PasswordTooLongError, hash_password
from app.db.session import async_session_factory, transaction

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
CODE_MAX_LENGTH = 50
CODE_SUFFIX_LENGTH = 7  # hyphen + 6 hex characters
MAX_CODE_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class TenantProvisionResult:
    tenant_id: UUID
    code: str
    name: str
    admin_email: str
    admin_role: str


def derive_tenant_code(name: str) -> str:
    """Build a unique-looking slug from the tenant name plus a short random suffix."""

    slug = _NON_ALNUM.sub("-", name.lower()).strip("-")
    max_slug_length = CODE_MAX_LENGTH - CODE_SUFFIX_LENGTH
    slug = slug[:max_slug_length].rstrip("-")
    suffix = secrets.token_hex(3)
    if not slug:
        return f"tenant-{suffix}"
    return f"{slug}-{suffix}"


def _normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized or "@" not in normalized:
        raise ValidationError("Admin email must be a valid email address")
    if len(normalized) > 255:
        raise ValidationError("Admin email must be at most 255 characters")
    return normalized


def _prompt_inputs() -> tuple[str, str, str, str]:
    tenant_name = normalize_required_text(input("Tenant name: "), field_name="Tenant name")
    admin_name = normalize_required_text(input("Admin name: "), field_name="Admin name")
    admin_email = _normalize_email(input("Admin email: "))
    password = getpass("Password: ")
    confirm = getpass("Confirm password: ")
    if not password:
        raise ValidationError("Password must not be empty")
    if password != confirm:
        raise ValidationError("Passwords do not match")
    return tenant_name, admin_name, admin_email, password


async def provision_tenant(
    *,
    tenant_name: str,
    admin_name: str,
    admin_email: str,
    password_hash: str,
) -> TenantProvisionResult:
    async with async_session_factory() as session, transaction(session):
        tenant: Tenant | None = None
        for _ in range(MAX_CODE_ATTEMPTS):
            try:
                async with session.begin_nested():
                    candidate = Tenant(
                        name=tenant_name,
                        code=derive_tenant_code(tenant_name),
                        settings={},
                        timezone="UTC",
                        status=TenantStatus.ACTIVE,
                    )
                    session.add(candidate)
                    await session.flush()
                    tenant = candidate
                break
            except IntegrityError:
                tenant = None

        if tenant is None:
            raise DuplicateResourceError("Could not allocate a unique tenant code")

        role = Role(
            tenant_id=tenant.id,
            name=SYSTEM_ADMIN_ROLE_NAME,
            description="Superadmin with all catalog permissions",
            is_system_role=True,
        )
        session.add(role)
        await session.flush()
        await grant_catalog_to_role(session, tenant.id, role.id)

        user = User(
            tenant_id=tenant.id,
            name=admin_name,
            email=admin_email,
            password_hash=password_hash,
            status=UserStatus.ACTIVE,
        )
        session.add(user)
        try:
            await session.flush()
        except IntegrityError as exc:
            raise DuplicateResourceError("A user with this email already exists") from exc

        session.add(UserRole(tenant_id=tenant.id, user_id=user.id, role_id=role.id))
        await session.flush()

        return TenantProvisionResult(
            tenant_id=tenant.id,
            code=tenant.code,
            name=tenant.name,
            admin_email=user.email,
            admin_role=role.name,
        )


def _print_summary(result: TenantProvisionResult) -> None:
    print("Tenant created successfully")
    print(f"  tenant_id:   {result.tenant_id}")
    print(f"  code:        {result.code}")
    print(f"  name:        {result.name}")
    print(f"  admin_email: {result.admin_email}")
    print(f"  admin_role:  {result.admin_role}")


def main() -> None:
    try:
        tenant_name, admin_name, admin_email, password = _prompt_inputs()
        password_hash = hash_password(password)
        result = asyncio.run(
            provision_tenant(
                tenant_name=tenant_name,
                admin_name=admin_name,
                admin_email=admin_email,
                password_hash=password_hash,
            )
        )
    except (PasswordTooLongError, ValidationError, DuplicateResourceError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        print("\nCancelled", file=sys.stderr)
        raise SystemExit(1) from None

    _print_summary(result)


if __name__ == "__main__":
    main()
