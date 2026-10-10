"""Financial category ORM (statement grouping for accounts)."""

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TenantModel


class FinancialCategory(TenantModel):
    __tablename__ = "financial_categories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_financial_categories_tenant_name"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    account_subtype: Mapped[str | None] = mapped_column(String(30), nullable=True)
