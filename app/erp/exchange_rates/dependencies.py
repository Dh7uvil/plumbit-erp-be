"""Exchange-rate slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.exchange_rates.service import CurrencyService, ExchangeRateService


def get_currency_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CurrencyService:
    return CurrencyService(session)


def get_exchange_rate_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ExchangeRateService:
    return ExchangeRateService(session)


CurrencyServiceDependency = Annotated[CurrencyService, Depends(get_currency_service)]
ExchangeRateServiceDependency = Annotated[ExchangeRateService, Depends(get_exchange_rate_service)]
