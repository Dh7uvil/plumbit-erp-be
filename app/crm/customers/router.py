"""Customer routes."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile, status

from app.auth.catalog import (
    CUSTOMER_CREATE,
    CUSTOMER_DELETE,
    CUSTOMER_EXPORT,
    CUSTOMER_HISTORY,
    CUSTOMER_IMPORT,
    CUSTOMER_READ,
    CUSTOMER_UPDATE,
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
from app.core.enums import InvoiceDocumentStatus
from app.crm.customers.dependencies import CustomerServiceDependency
from app.crm.customers.schemas import (
    CustomerCreate,
    CustomerExtraAddressCreate,
    CustomerExtraAddressResponse,
    CustomerFilter,
    CustomerResponse,
    CustomerUpdate,
)
from app.erp.accounting.customer_payments.dependencies import CustomerPaymentServiceDependency
from app.erp.accounting.customer_payments.schemas import CustomerPaymentResponse
from app.erp.accounting.open_items.dependencies import OpenItemsServiceDependency
from app.erp.accounting.open_items.schemas import OpenItemRow
from app.erp.accounting.reports.dependencies import ReportServiceDependency
from app.erp.accounting.reports.schemas import OutstandingSummary
from app.erp.credit_control.dependencies import CreditControlServiceDependency
from app.erp.credit_control.schemas import CreditExposure
from app.inventory_management.history.dependencies import HistoryServiceDependency
from app.inventory_management.history.schemas import (
    TradingHistoryFilter,
    TradingHistoryLine,
    TradingProductAggregate,
)

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("", response_model=ApiResponse[list[CustomerResponse]])
async def list_customers(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: CustomerServiceDependency,
    filters: Annotated[CustomerFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_READ))],
) -> ApiResponse[list[CustomerResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        tax_treatment=filters.tax_treatment.value if filters.tax_treatment else None,
        currency_id=filters.currency_id,
        company_type=filters.company_type.value if filters.company_type else None,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("/import/template")
async def customer_import_template(
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_IMPORT))],
):
    return template_response("customer")


@router.post("/import/preview", response_model=ApiResponse[ImportPreviewResponse])
async def customer_import_preview(
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_IMPORT))],
    file: Annotated[UploadFile, File()],
) -> ApiResponse[ImportPreviewResponse]:
    filename, content = await read_upload(file)
    return ApiResponse(data=preview_file("customer", filename=filename, content=content))


@router.post(
    "/import",
    response_model=ApiResponse[ImportResult],
    status_code=status.HTTP_201_CREATED,
)
async def customer_import(
    tenant: TenantContextDependency,
    service: CustomerServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_IMPORT))],
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
    return ApiResponse(data=result, message="Customers imported")


@router.get("/export")
async def customer_export(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: CustomerServiceDependency,
    filters: Annotated[CustomerFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_EXPORT))],
):
    rows, _total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        tax_treatment=filters.tax_treatment.value if filters.tax_treatment else None,
        currency_id=filters.currency_id,
        company_type=filters.company_type.value if filters.company_type else None,
        is_active=filters.is_active,
    )
    return export_response(
        "customer",
        ["name", "code", "trn", "email", "phone"],
        [[row.name, row.code, row.trn or "", "", ""] for row in rows],
    )


@router.post("", response_model=ApiResponse[CustomerResponse], status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate,
    tenant: TenantContextDependency,
    service: CustomerServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_CREATE))],
) -> ApiResponse[CustomerResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Customer created successfully")


@router.get("/{customer_id}", response_model=ApiResponse[CustomerResponse])
async def get_customer(
    customer_id: UUID,
    tenant: TenantContextDependency,
    service: CustomerServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_READ))],
) -> ApiResponse[CustomerResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, customer_id))


@router.patch("/{customer_id}", response_model=ApiResponse[CustomerResponse])
async def update_customer(
    customer_id: UUID,
    payload: CustomerUpdate,
    tenant: TenantContextDependency,
    service: CustomerServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_UPDATE))],
) -> ApiResponse[CustomerResponse]:
    row = await service.update(tenant.tenant_id, customer_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Customer updated successfully")


@router.delete("/{customer_id}", response_model=ApiResponse[CustomerResponse])
async def delete_customer(
    customer_id: UUID,
    tenant: TenantContextDependency,
    service: CustomerServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_DELETE))],
) -> ApiResponse[CustomerResponse]:
    row = await service.delete(tenant.tenant_id, customer_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Customer deleted successfully")


@router.post(
    "/{customer_id}/addresses",
    response_model=ApiResponse[CustomerExtraAddressResponse],
    status_code=status.HTTP_201_CREATED,
)
async def add_customer_address(
    customer_id: UUID,
    payload: CustomerExtraAddressCreate,
    tenant: TenantContextDependency,
    service: CustomerServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_UPDATE))],
) -> ApiResponse[CustomerExtraAddressResponse]:
    row = await service.add_extra_address(
        tenant.tenant_id, customer_id, payload, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Customer address added successfully")


@router.delete(
    "/{customer_id}/addresses/{extra_id}",
    response_model=ApiResponse[CustomerExtraAddressResponse],
)
async def delete_customer_address(
    customer_id: UUID,
    extra_id: UUID,
    tenant: TenantContextDependency,
    service: CustomerServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_UPDATE))],
) -> ApiResponse[CustomerExtraAddressResponse]:
    row = await service.delete_extra_address(
        tenant.tenant_id, customer_id, extra_id, actor_user_id=tenant.user_id
    )
    return ApiResponse(data=row, message="Customer address deleted successfully")


@router.get("/{customer_id}/products", response_model=ApiResponse[list[TradingProductAggregate]])
async def list_customer_products(
    customer_id: UUID,
    tenant: TenantContextDependency,
    history: HistoryServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_HISTORY))],
) -> ApiResponse[list[TradingProductAggregate]]:
    rows = await history.customer_products(tenant.tenant_id, customer_id)
    return ApiResponse(data=rows)


@router.get(
    "/{customer_id}/sales-history",
    response_model=ApiResponse[list[TradingHistoryLine]],
)
async def list_customer_sales_history(
    customer_id: UUID,
    tenant: TenantContextDependency,
    page: PaginationDependency,
    history: HistoryServiceDependency,
    filters: Annotated[TradingHistoryFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_HISTORY))],
) -> ApiResponse[list[TradingHistoryLine]]:
    rows, total = await history.customer_sales_history(
        tenant.tenant_id,
        customer_id,
        page=page,
        product_id=filters.product_id,
        warehouse_id=filters.warehouse_id,
        document_date_from=filters.document_date_from,
        document_date_to=filters.document_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.get("/{customer_id}/open-items", response_model=ApiResponse[list[OpenItemRow]])
async def list_customer_open_items(
    customer_id: UUID,
    tenant: TenantContextDependency,
    service: CustomerServiceDependency,
    open_items: OpenItemsServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_READ))],
) -> ApiResponse[list[OpenItemRow]]:
    await service.get(tenant.tenant_id, customer_id)
    rows = await open_items.list_ar_open_items(tenant.tenant_id, customer_id)
    return ApiResponse(data=rows)


@router.get("/{customer_id}/credit-exposure", response_model=ApiResponse[CreditExposure])
async def get_customer_credit_exposure(
    customer_id: UUID,
    tenant: TenantContextDependency,
    credit: CreditControlServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_READ))],
) -> ApiResponse[CreditExposure]:
    return ApiResponse(data=await credit.evaluate(tenant.tenant_id, customer_id))


@router.get("/{customer_id}/outstanding-summary", response_model=ApiResponse[OutstandingSummary])
async def get_customer_outstanding_summary(
    customer_id: UUID,
    tenant: TenantContextDependency,
    reports: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_READ))],
    as_of: Annotated[date | None, Query()] = None,
) -> ApiResponse[OutstandingSummary]:
    return ApiResponse(
        data=await reports.customer_outstanding(tenant.tenant_id, customer_id, as_of=as_of)
    )


@router.get(
    "/{customer_id}/payment-history",
    response_model=ApiResponse[list[CustomerPaymentResponse]],
)
async def get_customer_payment_history(
    customer_id: UUID,
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: CustomerServiceDependency,
    payments: CustomerPaymentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_READ))],
) -> ApiResponse[list[CustomerPaymentResponse]]:
    await service.get(tenant.tenant_id, customer_id)
    rows, total = await payments.list(
        tenant.tenant_id,
        page=page,
        status=InvoiceDocumentStatus.POSTED.value,
        customer_id=customer_id,
    )
    return paginated_response(rows, params=page, total=total)
