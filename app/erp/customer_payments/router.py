"""Customer receipt routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Request, status

from app.auth.catalog import (
    CUSTOMER_PAYMENT_CANCEL,
    CUSTOMER_PAYMENT_CREATE,
    CUSTOMER_PAYMENT_DELETE,
    CUSTOMER_PAYMENT_POST,
    CUSTOMER_PAYMENT_READ,
    CUSTOMER_PAYMENT_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.idempotency.service import hash_request, require_idempotency_key
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.common.utils.concurrency import require_document_version
from app.erp.accounting.ledger.schemas import JournalEntryResponse
from app.erp.accounting.open_items.schemas import PaymentAllocateRequest, PaymentCancelRequest
from app.erp.customer_payments.dependencies import CustomerPaymentServiceDependency
from app.erp.customer_payments.schemas import (
    CustomerPaymentCreate,
    CustomerPaymentFilter,
    CustomerPaymentResponse,
    CustomerPaymentUpdate,
)

router = APIRouter(prefix="/customer-payments", tags=["Customer Payments"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[CustomerPaymentResponse]])
async def list_customer_payments(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: CustomerPaymentServiceDependency,
    filters: Annotated[CustomerPaymentFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_PAYMENT_READ))],
) -> ApiResponse[list[CustomerPaymentResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        status=filters.status.value if filters.status else None,
        customer_id=filters.customer_id,
        proforma_invoice_id=filters.proforma_invoice_id,
        sales_order_id=filters.sales_order_id,
        currency_id=filters.currency_id,
        payment_method=filters.payment_method.value if filters.payment_method else None,
        payment_date_from=filters.payment_date_from,
        payment_date_to=filters.payment_date_to,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[CustomerPaymentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_customer_payment(
    payload: CustomerPaymentCreate,
    tenant: TenantContextDependency,
    service: CustomerPaymentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_PAYMENT_CREATE))],
) -> ApiResponse[CustomerPaymentResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Customer payment created successfully")


@router.get("/{payment_id}", response_model=ApiResponse[CustomerPaymentResponse])
async def get_customer_payment(
    payment_id: UUID,
    tenant: TenantContextDependency,
    service: CustomerPaymentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_PAYMENT_READ))],
) -> ApiResponse[CustomerPaymentResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, payment_id))


@router.patch("/{payment_id}", response_model=ApiResponse[CustomerPaymentResponse])
async def update_customer_payment(
    payment_id: UUID,
    payload: CustomerPaymentUpdate,
    tenant: TenantContextDependency,
    service: CustomerPaymentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_PAYMENT_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[CustomerPaymentResponse]:
    row = await service.update(
        tenant.tenant_id,
        payment_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match, body_version=payload.version),
    )
    return ApiResponse(data=row, message="Customer payment updated successfully")


@router.delete("/{payment_id}", response_model=ApiResponse[CustomerPaymentResponse])
async def delete_customer_payment(
    payment_id: UUID,
    tenant: TenantContextDependency,
    service: CustomerPaymentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_PAYMENT_DELETE))],
    if_match: IfMatch = None,
) -> ApiResponse[CustomerPaymentResponse]:
    row = await service.delete(
        tenant.tenant_id,
        payment_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
    )
    return ApiResponse(data=row, message="Customer payment deleted successfully")


@router.post("/{payment_id}/post", response_model=ApiResponse[CustomerPaymentResponse])
async def post_customer_payment(
    payment_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: CustomerPaymentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_PAYMENT_POST))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[CustomerPaymentResponse]:
    body = await request.body()
    row = await service.post(
        tenant.tenant_id,
        payment_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    message = "Customer payment posted successfully"
    if row.amount_unapplied > 0:
        message = "Customer payment posted; unapplied amount is held as an advance"
    return ApiResponse(data=row, message=message)


@router.post("/{payment_id}/cancel", response_model=ApiResponse[CustomerPaymentResponse])
async def cancel_customer_payment(
    payment_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: CustomerPaymentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_PAYMENT_CANCEL))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
    payload: Annotated[PaymentCancelRequest | None, Body()] = None,
) -> ApiResponse[CustomerPaymentResponse]:
    body_payload = payload or PaymentCancelRequest()
    body = await request.body()
    row = await service.cancel(
        tenant.tenant_id,
        payment_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(
            if_match=if_match, body_version=body_payload.version
        ),
        reason=body_payload.reason,
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Customer payment cancelled")


@router.post("/{payment_id}/allocate", response_model=ApiResponse[CustomerPaymentResponse])
async def allocate_customer_payment(
    payment_id: UUID,
    payload: PaymentAllocateRequest,
    tenant: TenantContextDependency,
    service: CustomerPaymentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_PAYMENT_POST))],
    if_match: IfMatch = None,
) -> ApiResponse[CustomerPaymentResponse]:
    row = await service.allocate(
        tenant.tenant_id,
        payment_id,
        payload.allocations,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(
            if_match=if_match, body_version=payload.version
        ),
    )
    return ApiResponse(data=row, message="Customer payment allocated")


@router.post("/{payment_id}/refund", response_model=ApiResponse[CustomerPaymentResponse])
async def refund_customer_payment(
    payment_id: UUID,
    request: Request,
    tenant: TenantContextDependency,
    service: CustomerPaymentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_PAYMENT_POST))],
    if_match: IfMatch = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[CustomerPaymentResponse]:
    body = await request.body()
    row = await service.refund(
        tenant.tenant_id,
        payment_id,
        actor_user_id=tenant.user_id,
        expected_version=require_document_version(if_match=if_match),
        idempotency_key=require_idempotency_key(idempotency_key),
        request_hash=hash_request(method=request.method, path=request.url.path, body=body),
        endpoint=request.url.path,
    )
    return ApiResponse(data=row, message="Unapplied receipt refunded")


@router.get("/{payment_id}/journal", response_model=ApiResponse[JournalEntryResponse])
async def get_customer_payment_journal(
    payment_id: UUID,
    tenant: TenantContextDependency,
    service: CustomerPaymentServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(CUSTOMER_PAYMENT_READ))],
) -> ApiResponse[JournalEntryResponse]:
    return ApiResponse(data=await service.journal(tenant.tenant_id, payment_id))
