"""Voucher slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.accounting.vouchers.service import VoucherService


def get_voucher_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> VoucherService:
    return VoucherService(session, actor_permissions=current_user.permissions)


VoucherServiceDependency = Annotated[VoucherService, Depends(get_voucher_service)]
