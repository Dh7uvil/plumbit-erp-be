"""GRN charge adjustment tables and permissions.

Revision ID: m9h0i1j2k345
Revises: l8g9h0i1j234
Create Date: 2026-09-29 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "m9h0i1j2k345"
down_revision: str | None = "l8g9h0i1j234"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
_MONEY = sa.Numeric(18, 4)


def upgrade() -> None:
    op.create_table(
        "goods_receipt_charge_adjustments",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("document_number", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), server_default=sa.text("'DRAFT'"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_posted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("document_date", sa.Date(), nullable=False),
        sa.Column("goods_receipt_id", UUID, nullable=False),
        sa.Column("branch_id", UUID, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by", UUID, nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", UUID, nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("updated_by", UUID, nullable=True),
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
        sa.ForeignKeyConstraint(["goods_receipt_id"], ["goods_receipts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_grn_charge_adjustments_tenant_id_document_number_active",
        "goods_receipt_charge_adjustments",
        ["tenant_id", "document_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_grn_charge_adjustments_tenant_id_status",
        "goods_receipt_charge_adjustments",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_grn_charge_adjustments_tenant_id_document_date",
        "goods_receipt_charge_adjustments",
        ["tenant_id", "document_date"],
    )
    op.create_index(
        "ix_grn_charge_adjustments_goods_receipt_id",
        "goods_receipt_charge_adjustments",
        ["goods_receipt_id"],
    )
    op.create_index(
        "ix_grn_charge_adjustments_tenant_id",
        "goods_receipt_charge_adjustments",
        ["tenant_id"],
    )

    op.create_table(
        "goods_receipt_charge_adjustment_lines",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("goods_receipt_charge_adjustment_id", UUID, nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("goods_receipt_charge_id", UUID, nullable=False),
        sa.Column("adjustment_amount", _MONEY, nullable=False),
        sa.Column("base_adjustment_amount", _MONEY, server_default=sa.text("0"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["goods_receipt_charge_adjustment_id"],
            ["goods_receipt_charge_adjustments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["goods_receipt_charge_id"],
            ["goods_receipt_charges.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "goods_receipt_charge_adjustment_id",
            "line_number",
            name="uq_grn_charge_adjustment_lines_header_line_number",
        ),
    )
    op.create_index(
        "ix_grn_charge_adjustment_lines_adjustment_id",
        "goods_receipt_charge_adjustment_lines",
        ["goods_receipt_charge_adjustment_id"],
    )
    op.create_index(
        "ix_grn_charge_adjustment_lines_goods_receipt_charge_id",
        "goods_receipt_charge_adjustment_lines",
        ["goods_receipt_charge_id"],
    )
    op.create_index(
        "ix_grn_charge_adjustment_lines_tenant_id",
        "goods_receipt_charge_adjustment_lines",
        ["tenant_id"],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO document_sequences (
                id, tenant_id, document_type, series, fiscal_year, prefix, padding,
                next_number, is_active, created_at, updated_at
            )
            SELECT gen_random_uuid(), t.id, 'GRN_CHARGE_ADJUSTMENT', 'GCA',
                EXTRACT(YEAR FROM CURRENT_DATE)::int, 'GCA', 6, 1, true, now(), now()
            FROM tenants t
            WHERE NOT EXISTS (
                SELECT 1 FROM document_sequences ds
                WHERE ds.tenant_id = t.id
                  AND ds.document_type = 'GRN_CHARGE_ADJUSTMENT'
                  AND ds.deleted_at IS NULL
            )
            """
        )
    )

    from app.auth.catalog import parsed_catalog_permissions

    bind = op.get_bind()
    catalog = parsed_catalog_permissions()
    for tenant_id, in bind.execute(sa.text("SELECT id FROM tenants")).fetchall():
        existing = {
            (row[0], row[1], row[2])
            for row in bind.execute(
                sa.text(
                    "SELECT module, resource, action FROM permissions WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).fetchall()
        }
        for permission in catalog:
            if permission.resource != "grn_charge_adjustment":
                continue
            key = (permission.module, permission.resource, permission.action)
            if key in existing:
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
                    "module": permission.module,
                    "resource": permission.resource,
                    "action": permission.action,
                },
            )
        bind.execute(
            sa.text(
                """
                INSERT INTO role_permissions (tenant_id, role_id, permission_id)
                SELECT :tenant_id, r.id, p.id
                FROM roles r
                JOIN permissions p
                  ON p.tenant_id = r.tenant_id
                 AND p.resource = 'grn_charge_adjustment'
                WHERE r.tenant_id = :tenant_id
                  AND r.name = 'Superadmin'
                  AND NOT EXISTS (
                      SELECT 1 FROM role_permissions rp
                      WHERE rp.tenant_id = :tenant_id
                        AND rp.role_id = r.id
                        AND rp.permission_id = p.id
                  )
                """
            ),
            {"tenant_id": tenant_id},
        )


def downgrade() -> None:
    op.drop_table("goods_receipt_charge_adjustment_lines")
    op.drop_table("goods_receipt_charge_adjustments")
    op.execute(
        sa.text(
            "DELETE FROM document_sequences WHERE document_type = 'GRN_CHARGE_ADJUSTMENT'"
        )
    )
    op.execute(sa.text("DELETE FROM permissions WHERE resource = 'grn_charge_adjustment'"))
