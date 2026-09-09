"""Goods receipt slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.inventory_management.goods_receipts.service import GoodsReceiptService


def get_goods_receipt_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> GoodsReceiptService:
    return GoodsReceiptService(session, actor_permissions=current_user.permissions)


GoodsReceiptServiceDependency = Annotated[GoodsReceiptService, Depends(get_goods_receipt_service)]
