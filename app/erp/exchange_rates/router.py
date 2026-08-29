"""Currency and daily exchange-rate routes."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.auth.catalog import (
    CURRENCY_CREATE,
    CURRENCY_DELETE,
    CURRENCY_READ,
    CURRENCY_UPDATE,
    EXCHANGE_RATE_CREATE,
    EXCHANGE_RATE_READ,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.erp.exchange_rates.dependencies import (
    CurrencyServiceDependency,
    ExchangeRateServiceDependency,
)
from app.erp.exchange_rates.schemas import (
    CurrencyCreate,
    CurrencyFilter,
    CurrencyResponse,
    CurrencyUpdate,
    ExchangeRateResolveResponse,
    ExchangeRateResponse,
    ExchangeRateUpsert,
)

currencies_router = APIRouter(prefix="/currencies", tags=["Currencies"])
exchange_rates_router = APIRouter(prefix="/exchange-rates", tags=["Exchange Rates"])
router = APIRouter()


@currencies_router.get("", response_model=ApiResponse[list[CurrencyResponse]])
async def list_currencies(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: CurrencyServiceDependency,
    filters: Annotated[CurrencyFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CURRENCY_READ))],
) -> ApiResponse[list[CurrencyResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        is_base=filters.is_base,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


@currencies_router.post(
    "",
    response_model=ApiResponse[CurrencyResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_currency(
    payload: CurrencyCreate,
    tenant: TenantContextDependency,
    service: CurrencyServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CURRENCY_CREATE))],
) -> ApiResponse[CurrencyResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Currency created successfully")


@currencies_router.get("/{currency_id}", response_model=ApiResponse[CurrencyResponse])
async def get_currency(
    currency_id: UUID,
    tenant: TenantContextDependency,
    service: CurrencyServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CURRENCY_READ))],
) -> ApiResponse[CurrencyResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, currency_id))


@currencies_router.patch("/{currency_id}", response_model=ApiResponse[CurrencyResponse])
async def update_currency(
    currency_id: UUID,
    payload: CurrencyUpdate,
    tenant: TenantContextDependency,
    service: CurrencyServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CURRENCY_UPDATE))],
) -> ApiResponse[CurrencyResponse]:
    row = await service.update(tenant.tenant_id, currency_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Currency updated successfully")


@currencies_router.delete("/{currency_id}", response_model=ApiResponse[CurrencyResponse])
async def delete_currency(
    currency_id: UUID,
    tenant: TenantContextDependency,
    service: CurrencyServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CURRENCY_DELETE))],
) -> ApiResponse[CurrencyResponse]:
    row = await service.delete(tenant.tenant_id, currency_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Currency deleted successfully")


@exchange_rates_router.get("", response_model=ApiResponse[list[ExchangeRateResponse]])
async def list_exchange_rates(
    tenant: TenantContextDependency,
    service: ExchangeRateServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(EXCHANGE_RATE_READ))],
    effective_date: Annotated[date | None, Query()] = None,
) -> ApiResponse[list[ExchangeRateResponse]]:
    rows = await service.list_for_date(tenant.tenant_id, effective_date=effective_date)
    return ApiResponse(data=rows)


@exchange_rates_router.get("/resolve", response_model=ApiResponse[ExchangeRateResolveResponse])
async def resolve_exchange_rate(
    tenant: TenantContextDependency,
    service: ExchangeRateServiceDependency,
    from_currency_id: UUID,
    _: Annotated[CurrentUser, Depends(require_permission(EXCHANGE_RATE_READ))],
    on_date: Annotated[date | None, Query()] = None,
) -> ApiResponse[ExchangeRateResolveResponse]:
    resolved = await service.resolve(
        tenant.tenant_id,
        from_currency_id=from_currency_id,
        on_date=on_date,
    )
    return ApiResponse(data=resolved)


@exchange_rates_router.put("", response_model=ApiResponse[ExchangeRateResponse])
async def upsert_exchange_rate(
    payload: ExchangeRateUpsert,
    tenant: TenantContextDependency,
    service: ExchangeRateServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(EXCHANGE_RATE_CREATE))],
) -> ApiResponse[ExchangeRateResponse]:
    row = await service.upsert(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Exchange rate saved successfully")


router.include_router(currencies_router)
router.include_router(exchange_rates_router)
