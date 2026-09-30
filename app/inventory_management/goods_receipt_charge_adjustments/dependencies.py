"""GRN charge adjustment slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.inventory_management.goods_receipt_charge_adjustments.service import (
    GoodsReceiptChargeAdjustmentService,
)


def get_goods_receipt_charge_adjustment_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> GoodsReceiptChargeAdjustmentService:
    return GoodsReceiptChargeAdjustmentService(
        session, actor_permissions=current_user.permissions
    )


GoodsReceiptChargeAdjustmentServiceDependency = Annotated[
    GoodsReceiptChargeAdjustmentService,
    Depends(get_goods_receipt_charge_adjustment_service),
]
