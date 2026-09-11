"""Product routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile, status

from app.auth.catalog import (
    PRODUCT_CREATE,
    PRODUCT_DELETE,
    PRODUCT_EXPORT,
    PRODUCT_HISTORY,
    PRODUCT_IMPORT,
    PRODUCT_READ,
    PRODUCT_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import require_idempotency_key
from app.common.imex.http import parse_mapping_json, read_upload
from app.common.imex.schemas import ImportPreviewResponse, ImportResult
from app.common.imex.service import export_response, preview_file, template_response
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.inventory_management.history.dependencies import HistoryServiceDependency
from app.inventory_management.history.schemas import (
    TradingHistoryFilter,
    TradingHistoryLine,
    TradingPartyAggregate,
)
from app.inventory_management.products.dependencies import ProductServiceDependency
from app.inventory_management.products.schemas import (
    ProductCreate,
    ProductFilter,
    ProductResponse,
    ProductUpdate,
)

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("", response_model=ApiResponse[list[ProductResponse]])
async def list_products(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: ProductServiceDependency,
    filters: Annotated[ProductFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(PRODUCT_READ))],
) -> ApiResponse[list[ProductResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        item_type=filters.item_type.value if filters.item_type else None,
        category_id=filters.category_id,
        unit_id=filters.unit_id,
        tax_id=filters.tax_id,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("/import/template")
async def product_import_template(
    _: Annotated[CurrentUser, Depends(require_permission(PRODUCT_IMPORT))],
):
    return template_response("product")


@router.post("/import/preview", response_model=ApiResponse[ImportPreviewResponse])
async def product_import_preview(
    _: Annotated[CurrentUser, Depends(require_permission(PRODUCT_IMPORT))],
    file: Annotated[UploadFile, File()],
) -> ApiResponse[ImportPreviewResponse]:
    filename, content = await read_upload(file)
    return ApiResponse(data=preview_file("product", filename=filename, content=content))


@router.post(
    "/import",
    response_model=ApiResponse[ImportResult],
    status_code=status.HTTP_201_CREATED,
)
async def product_import(
    tenant: TenantContextDependency,
    service: ProductServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PRODUCT_IMPORT))],
    file: Annotated[UploadFile, File()],
    mapping: Annotated[str | None, Form()] = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[ImportResult]:
    require_idempotency_key(idempotency_key)
    filename, content = await read_upload(file)
    result = await service.import_rows(
        tenant.tenant_id,
        filename=filename,
        content=content,
        mapping=parse_mapping_json(mapping),
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=result, message="Products imported")


@router.get("/export")
async def product_export(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: ProductServiceDependency,
    filters: Annotated[ProductFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(PRODUCT_EXPORT))],
):
    rows, _total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        item_type=filters.item_type.value if filters.item_type else None,
        category_id=filters.category_id,
        unit_id=filters.unit_id,
        tax_id=filters.tax_id,
        is_active=filters.is_active,
    )
    return export_response(
        "product",
        ["sku", "name", "selling_rate", "purchase_rate"],
        [[row.sku, row.name, row.selling_rate, row.purchase_rate] for row in rows],
    )


@router.post("", response_model=ApiResponse[ProductResponse], status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    tenant: TenantContextDependency,
    service: ProductServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PRODUCT_CREATE))],
) -> ApiResponse[ProductResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Product created successfully")


@router.get("/{product_id}", response_model=ApiResponse[ProductResponse])
async def get_product(
    product_id: UUID,
    tenant: TenantContextDependency,
    service: ProductServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PRODUCT_READ))],
) -> ApiResponse[ProductResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, product_id))


@router.patch("/{product_id}", response_model=ApiResponse[ProductResponse])
async def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    tenant: TenantContextDependency,
    service: ProductServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PRODUCT_UPDATE))],
) -> ApiResponse[ProductResponse]:
    row = await service.update(tenant.tenant_id, product_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Product updated successfully")


@router.delete("/{product_id}", response_model=ApiResponse[ProductResponse])
async def delete_product(
    product_id: UUID,
    tenant: TenantContextDependency,
    service: ProductServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PRODUCT_DELETE))],
) -> ApiResponse[ProductResponse]:
    row = await service.delete(tenant.tenant_id, product_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Product deleted successfully")


@router.get("/{product_id}/customers", response_model=ApiResponse[list[TradingPartyAggregate]])
async def list_product_customers(
    product_id: UUID,
    tenant: TenantContextDependency,
    history: HistoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PRODUCT_HISTORY))],
) -> ApiResponse[list[TradingPartyAggregate]]:
    rows = await history.product_customers(tenant.tenant_id, product_id)
    return ApiResponse(data=rows)


@router.get(
    "/{product_id}/sales-history",
    response_model=ApiResponse[list[TradingHistoryLine]],
)
async def list_product_sales_history(
    product_id: UUID,
    tenant: TenantContextDependency,
    page: PaginationDependency,
    history: HistoryServiceDependency,
    filters: Annotated[TradingHistoryFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(PRODUCT_HISTORY))],
) -> ApiResponse[list[TradingHistoryLine]]:
    rows, total = await history.product_sales_history(
        tenant.tenant_id,
        product_id,
        page=page,
        party_id=filters.party_id,
        warehouse_id=filters.warehouse_id,
        document_date_from=filters.document_date_from,
        document_date_to=filters.document_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.get(
    "/{product_id}/purchase-history",
    response_model=ApiResponse[list[TradingHistoryLine]],
)
async def list_product_purchase_history(
    product_id: UUID,
    tenant: TenantContextDependency,
    page: PaginationDependency,
    history: HistoryServiceDependency,
    filters: Annotated[TradingHistoryFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(PRODUCT_HISTORY))],
) -> ApiResponse[list[TradingHistoryLine]]:
    rows, total = await history.product_purchase_history(
        tenant.tenant_id,
        product_id,
        page=page,
        party_id=filters.party_id,
        warehouse_id=filters.warehouse_id,
        document_date_from=filters.document_date_from,
        document_date_to=filters.document_date_to,
    )
    return paginated_response(rows, params=page, total=total)
