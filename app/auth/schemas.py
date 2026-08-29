"""Request and response schemas for the access-management slice."""

from datetime import date, datetime
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import (
    blank_to_none,
    normalize_currency_code,
    normalize_required_text,
    optional_uuid_input,
)
from app.core.enums import BranchStatus, EmployeeStatus, UserStatus

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 72


def _normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized or "@" not in normalized:
        raise ValueError("email must be a valid email address")
    if len(normalized) > 255:
        raise ValueError("email must be at most 255 characters")
    return normalized


def _normalize_optional_phone(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


class TenantPublicResponse(BaseModel):
    """Public tenant row for the login-screen selector."""

    tenant_id: UUID
    name: str
    logo_url: str | None = None


class LoginRequest(BaseModel):
    tenant_id: UUID
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RoleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    is_system_role: bool


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class AddressPayload(BaseModel):
    address_line_1: str | None = Field(default=None, max_length=250)
    address_line_2: str | None = Field(default=None, max_length=250)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    country_code: str | None = Field(default=None, max_length=10)
    postal_code: str | None = Field(default=None, max_length=30)

    @field_validator(
        "address_line_1",
        "address_line_2",
        "city",
        "state",
        "country",
        "country_code",
        "postal_code",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class AddressResponse(AddressPayload):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


class BranchSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str


class DepartmentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str


class EmployeeUpsert(BaseModel):
    employee_code: str = Field(min_length=1, max_length=50)
    branch_id: UUID | None = None
    department_id: UUID | None = None
    designation: str | None = Field(default=None, max_length=150)
    joining_date: date | None = None

    @field_validator("employee_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return normalize_required_text(value, field_name="employee_code")

    @field_validator("designation")
    @classmethod
    def normalize_designation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class EmployeeSummary(BaseModel):
    id: UUID
    employee_code: str
    designation: str | None
    joining_date: date | None
    status: EmployeeStatus
    branch: BranchSummary | None = None
    department: DepartmentSummary | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    email: str
    phone: str | None
    status: UserStatus
    last_login_at: datetime | None
    employee_id: UUID | None
    created_at: datetime
    updated_at: datetime
    roles: list[RoleSummary] = Field(default_factory=list)
    employee: EmployeeSummary | None = None


class UserDetailResponse(UserResponse):
    roles: list[RoleSummary] = Field(default_factory=list)


class MeResponse(UserDetailResponse):
    permissions: list[str] = Field(default_factory=list)


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    phone: str | None = Field(default=None, max_length=50)
    status: UserStatus = UserStatus.ACTIVE
    role_ids: list[UUID] = Field(default_factory=list)
    employee: EmployeeUpsert | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        return _normalize_optional_phone(value)


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    status: UserStatus | None = None
    employee: EmployeeUpsert | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_email(value)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        return _normalize_optional_phone(value)


class AssignRolesRequest(BaseModel):
    role_ids: list[UUID]


class UserFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "email", "status", "last_login_at"}
    )

    status: UserStatus | None = Field(
        default=None,
        description="Account status: ACTIVE, INVITED, DISABLED.",
    )
    role_id: UUID | None = Field(
        default=None,
        description="Users assigned to this role. Combined with role_ids when both are set.",
    )
    role_ids: list[UUID] | None = Field(
        default=None,
        description="Users assigned to any of these roles.",
    )
    department_id: UUID | None = Field(
        default=None,
        description="Users whose employee profile belongs to this department.",
    )
    branch_id: UUID | None = Field(
        default=None,
        description="Users whose employee profile belongs to this branch.",
    )
    designation: str | None = Field(
        default=None,
        max_length=150,
        description="Case-insensitive match on employee designation.",
    )
    joining_date: date | None = Field(
        default=None,
        description="Exact employee joining date.",
    )
    joining_date_from: date | None = Field(
        default=None,
        description="Employee joining date on or after this day.",
    )
    joining_date_to: date | None = Field(
        default=None,
        description="Employee joining date on or before this day.",
    )
    employee_status: EmployeeStatus | None = Field(
        default=None,
        description="Employee HR status: ACTIVE or INACTIVE.",
    )
    employee_code: str | None = Field(
        default=None,
        max_length=50,
        description="Case-insensitive match on employee code.",
    )
    last_login_from: datetime | None = Field(
        default=None,
        description="Users whose last_login_at is on or after this timestamp.",
    )
    last_login_to: datetime | None = Field(
        default=None,
        description="Users whose last_login_at is on or before this timestamp.",
    )
    phone: str | None = Field(
        default=None,
        max_length=50,
        description="Case-insensitive match on user phone.",
    )
    manager_id: UUID | None = Field(
        default=None,
        description="Users in a department managed by this user.",
    )

    @field_validator("designation", "employee_code", "phone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("role_ids", mode="before")
    @classmethod
    def parse_role_ids(cls, value: object) -> object:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",") if part.strip()]
            return parts or None
        if isinstance(value, UUID):
            return [value]
        if isinstance(value, (list, tuple)):
            return list(value)
        return None

    @model_validator(mode="after")
    def validate_user_filter_ranges(self) -> "UserFilter":
        if (
            self.joining_date_from is not None
            and self.joining_date_to is not None
            and self.joining_date_from > self.joining_date_to
        ):
            raise ValueError("joining_date_from must be before or equal to joining_date_to")
        if (
            self.last_login_from is not None
            and self.last_login_to is not None
            and self.last_login_from > self.last_login_to
        ):
            raise ValueError("last_login_from must be before or equal to last_login_to")
        return self

    def collected_role_ids(self) -> list[UUID]:
        unique: dict[UUID, None] = {role_id: None for role_id in self.role_ids or []}
        if self.role_id is not None:
            unique[self.role_id] = None
        return list(unique)


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    is_system_role: bool
    user_count: int = 0
    created_at: datetime
    updated_at: datetime


class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    module: str
    resource: str
    action: str
    created_at: datetime
    updated_at: datetime
    code: str = ""

    @model_validator(mode="after")
    def populate_code(self) -> "PermissionResponse":
        self.code = f"{self.module}.{self.resource}.{self.action}"
        return self


class RoleDetailResponse(RoleResponse):
    permissions: list[PermissionResponse] = Field(default_factory=list)


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    permission_ids: list[UUID] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SetRolePermissionsRequest(BaseModel):
    permission_ids: list[UUID]


class RoleFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at", "name"})


class PermissionFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "module", "resource", "action"}
    )

    module: str | None = None


class PermissionMatrixAction(BaseModel):
    id: UUID
    action: str
    code: str
    granted: bool


class PermissionMatrixResource(BaseModel):
    resource: str
    actions: list[PermissionMatrixAction]


class PermissionMatrixModule(BaseModel):
    module: str
    resources: list[PermissionMatrixResource]


class PermissionMatrixResponse(BaseModel):
    modules: list[PermissionMatrixModule]


class TenantSettings(BaseModel):
    """Prototype extras stored on ``tenants.settings`` JSONB."""

    model_config = ConfigDict(extra="allow")

    industry: str | None = Field(default=None, max_length=150)
    website: str | None = Field(default=None, max_length=255)
    contact_email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    founded: str | None = Field(default=None, max_length=20)
    fiscal_year_start: str | None = Field(default=None, max_length=50)
    default_currency: str | None = Field(default=None, max_length=3)
    quotation_requires_approval: bool = True
    headquarters: AddressPayload | None = None

    @field_validator("industry", "website", "founded", "fiscal_year_start", "phone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("contact_email")
    @classmethod
    def normalize_contact_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if "@" not in normalized:
            raise ValueError("contact_email must be a valid email address")
        return normalized

    @field_validator("default_currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        return normalize_currency_code(stripped)


class TenantCurrentResponse(BaseModel):
    id: UUID
    name: str
    code: str
    timezone: str
    status: str
    logo_url: str | None = None
    industry: str | None = None
    website: str | None = None
    contact_email: str | None = None
    phone: str | None = None
    founded: str | None = None
    fiscal_year_start: str | None = None
    default_currency: str | None = None
    default_currency_id: UUID | None = None
    quotation_requires_approval: bool = True
    headquarters: AddressPayload | None = None
    users_count: int
    departments_count: int
    branches_count: int
    created_at: datetime
    updated_at: datetime


class TenantCurrentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    industry: str | None = Field(default=None, max_length=150)
    website: str | None = Field(default=None, max_length=255)
    contact_email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    founded: str | None = Field(default=None, max_length=20)
    fiscal_year_start: str | None = Field(default=None, max_length=50)
    default_currency: str | None = Field(default=None, max_length=3)
    default_currency_id: UUID | None = None
    quotation_requires_approval: bool | None = None
    headquarters: AddressPayload | None = None

    @field_validator(
        "timezone",
        "industry",
        "website",
        "contact_email",
        "phone",
        "founded",
        "fiscal_year_start",
        "default_currency",
        mode="before",
    )
    @classmethod
    def coerce_blank_optional_text(cls, value: object) -> object:
        return blank_to_none(value)

    @field_validator("default_currency_id", mode="before")
    @classmethod
    def coerce_optional_currency_id(cls, value: object) -> object:
        return optional_uuid_input(value)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @field_validator("timezone", "industry", "website", "founded", "fiscal_year_start", "phone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("contact_email")
    @classmethod
    def normalize_contact_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if "@" not in normalized:
            raise ValueError("contact_email must be a valid email address")
        return normalized

    @field_validator("default_currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        return normalize_currency_code(stripped)


class BranchFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "code", "status"}
    )

    status: BranchStatus | None = None


class BranchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=50)
    status: BranchStatus = BranchStatus.ACTIVE
    phone: str | None = Field(default=None, max_length=50)
    timezone: str | None = Field(default=None, max_length=100)
    default_currency_id: UUID | None = None
    address: AddressPayload | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return normalize_required_text(value, field_name="code")

    @field_validator("phone", "timezone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class BranchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    status: BranchStatus | None = None
    phone: str | None = Field(default=None, max_length=50)
    timezone: str | None = Field(default=None, max_length=100)
    default_currency_id: UUID | None = None
    address: AddressPayload | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="code")

    @field_validator("phone", "timezone")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class BranchResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    code: str
    status: BranchStatus
    phone: str | None
    timezone: str | None
    default_currency_id: UUID | None = None
    address: AddressResponse | None = None
    employee_count: int = 0
    created_at: datetime
    updated_at: datetime


class DepartmentFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "code"}
    )

    branch_id: UUID | None = None


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: str = Field(min_length=1, max_length=50)
    branch_id: UUID
    manager_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return normalize_required_text(value, field_name="code")


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    branch_id: UUID | None = None
    manager_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="code")


class DepartmentResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    code: str
    branch_id: UUID
    branch: BranchSummary | None = None
    manager_id: UUID | None
    manager: UserSummary | None = None
    employee_count: int = 0
    created_at: datetime
    updated_at: datetime


class AuditLogFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "action", "module"})

    module: str | None = None
    action: str | None = None
    user_id: UUID | None = None


class AuditLogUserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class AuditLogResponse(BaseModel):
    id: UUID
    timestamp: datetime
    user: AuditLogUserSummary | None = None
    action: str
    entity_type: str
    entity_id: UUID | None
    module: str
    ip_address: str | None
    status: str


class AuditLogSummaryResponse(BaseModel):
    total_events: int
    unique_users: int
    failed_attempts: int
    admin_actions: int
