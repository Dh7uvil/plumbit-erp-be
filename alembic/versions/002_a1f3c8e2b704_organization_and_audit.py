"""organization and audit

Revision ID: a1f3c8e2b704
Revises: c4e8a1b7d902
Create Date: 2026-08-20 10:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.auth.catalog import SYSTEM_ADMIN_ROLE_NAME, parsed_identity_permissions

revision: str = "a1f3c8e2b704"
down_revision: str | Sequence[str] | None = "c4e8a1b7d902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this revision."""
    op.create_table(
        "addresses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("address_type", sa.String(length=30), nullable=False),
        sa.Column("address_line_1", sa.String(length=250), nullable=True),
        sa.Column("address_line_2", sa.String(length=250), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("state", sa.String(length=100), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("country_code", sa.String(length=10), nullable=True),
        sa.Column("postal_code", sa.String(length=30), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_addresses_tenant_id", "addresses", ["tenant_id"], unique=False)

    op.create_table(
        "branches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("address_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("default_currency_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("timezone", sa.String(length=100), nullable=True),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'ACTIVE'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["address_id"], ["addresses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_branches_tenant_id", "branches", ["tenant_id"], unique=False)
    op.create_index("ix_branches_address_id", "branches", ["address_id"], unique=False)
    op.create_index(
        "uq_branches_tenant_id_code_active",
        "branches",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "departments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("manager_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["manager_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_departments_tenant_id", "departments", ["tenant_id"], unique=False)
    op.create_index("ix_departments_branch_id", "departments", ["branch_id"], unique=False)
    op.create_index("ix_departments_manager_id", "departments", ["manager_id"], unique=False)
    op.create_index(
        "uq_departments_tenant_id_code_active",
        "departments",
        ["tenant_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "employees",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("employee_code", sa.String(length=50), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("designation", sa.String(length=150), nullable=True),
        sa.Column("joining_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'ACTIVE'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_employees_tenant_id", "employees", ["tenant_id"], unique=False)
    op.create_index("ix_employees_user_id", "employees", ["user_id"], unique=False)
    op.create_index("ix_employees_branch_id", "employees", ["branch_id"], unique=False)
    op.create_index("ix_employees_department_id", "employees", ["department_id"], unique=False)
    op.create_index(
        "uq_employees_tenant_id_employee_code_active",
        "employees",
        ["tenant_id", "employee_code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_foreign_key(
        "fk_users_employee_id_employees",
        "users",
        "employees",
        ["employee_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("module", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("old_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'SUCCESS'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"], unique=False)
    op.create_index(
        "ix_audit_logs_tenant_id_created_at",
        "audit_logs",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_logs_tenant_id_action",
        "audit_logs",
        ["tenant_id", "action"],
        unique=False,
    )
    op.create_index(
        "ix_audit_logs_tenant_id_module",
        "audit_logs",
        ["tenant_id", "module"],
        unique=False,
    )
    op.create_index(
        "ix_audit_logs_tenant_id_user_id",
        "audit_logs",
        ["tenant_id", "user_id"],
        unique=False,
    )

    _backfill_identity_permissions()


def _backfill_identity_permissions() -> None:
    """Insert missing catalog rows and attach them to each tenant's Admin role."""

    bind = op.get_bind()
    tenants = bind.execute(sa.text("SELECT id FROM tenants")).fetchall()
    catalog = parsed_identity_permissions()

    for (tenant_id,) in tenants:
        existing = bind.execute(
            sa.text(
                "SELECT module, resource, action FROM permissions WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        ).fetchall()
        existing_keys = {(row.module, row.resource, row.action) for row in existing}
        for parsed in catalog:
            key = (parsed.module, parsed.resource, parsed.action)
            if key in existing_keys:
                continue
            bind.execute(
                sa.text(
                    """
                    INSERT INTO permissions (tenant_id, module, resource, action)
                    VALUES (:tenant_id, :module, :resource, :action)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "module": parsed.module,
                    "resource": parsed.resource,
                    "action": parsed.action,
                },
            )

        admin = bind.execute(
            sa.text(
                """
                SELECT id FROM roles
                WHERE tenant_id = :tenant_id
                  AND name = :name
                  AND is_system_role = true
                """
            ),
            {"tenant_id": tenant_id, "name": SYSTEM_ADMIN_ROLE_NAME},
        ).fetchone()
        if admin is None:
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO role_permissions (tenant_id, role_id, permission_id)
                SELECT :tenant_id, :role_id, p.id
                FROM permissions p
                WHERE p.tenant_id = :tenant_id
                  AND NOT EXISTS (
                    SELECT 1
                    FROM role_permissions rp
                    WHERE rp.tenant_id = :tenant_id
                      AND rp.role_id = :role_id
                      AND rp.permission_id = p.id
                  )
                """
            ),
            {"tenant_id": tenant_id, "role_id": admin.id},
        )


def downgrade() -> None:
    """Revert this revision."""
    op.drop_index("ix_audit_logs_tenant_id_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_id_module", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_id_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_id_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_id", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_constraint("fk_users_employee_id_employees", "users", type_="foreignkey")
    op.drop_index("uq_employees_tenant_id_employee_code_active", table_name="employees")
    op.drop_index("ix_employees_department_id", table_name="employees")
    op.drop_index("ix_employees_branch_id", table_name="employees")
    op.drop_index("ix_employees_user_id", table_name="employees")
    op.drop_index("ix_employees_tenant_id", table_name="employees")
    op.drop_table("employees")
    op.drop_index("uq_departments_tenant_id_code_active", table_name="departments")
    op.drop_index("ix_departments_manager_id", table_name="departments")
    op.drop_index("ix_departments_branch_id", table_name="departments")
    op.drop_index("ix_departments_tenant_id", table_name="departments")
    op.drop_table("departments")
    op.drop_index("uq_branches_tenant_id_code_active", table_name="branches")
    op.drop_index("ix_branches_address_id", table_name="branches")
    op.drop_index("ix_branches_tenant_id", table_name="branches")
    op.drop_table("branches")
    op.drop_index("ix_addresses_tenant_id", table_name="addresses")
    op.drop_table("addresses")
