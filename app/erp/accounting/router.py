"""Accounting master routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.catalog import (
    DOCUMENT_SEQUENCE_CREATE,
    DOCUMENT_SEQUENCE_DELETE,
    DOCUMENT_SEQUENCE_READ,
    DOCUMENT_SEQUENCE_UPDATE,
    PAYMENT_TERM_CREATE,
    PAYMENT_TERM_DELETE,
    PAYMENT_TERM_READ,
    PAYMENT_TERM_UPDATE,
    TAX_CREATE,
    TAX_DELETE,
    TAX_READ,
    TAX_UPDATE,
    TERMS_TEMPLATE_CREATE,
    TERMS_TEMPLATE_DELETE,
    TERMS_TEMPLATE_READ,
    TERMS_TEMPLATE_UPDATE,
)
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.pagination import PaginationDependency
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.pagination import paginated_response
from app.common.schemas.response import ApiResponse
from app.erp.accounting.dependencies import (
    DocumentSequenceServiceDependency,
    PaymentTermServiceDependency,
    TaxServiceDependency,
    TermsTemplateServiceDependency,
)
from app.erp.accounting.schemas import (
    DocumentSequenceCreate,
    DocumentSequenceFilter,
    DocumentSequenceResponse,
    DocumentSequenceUpdate,
    PaymentTermCreate,
    PaymentTermFilter,
    PaymentTermResponse,
    PaymentTermUpdate,
    TaxCreate,
    TaxFilter,
    TaxResponse,
    TaxUpdate,
    TermsTemplateCreate,
    TermsTemplateFilter,
    TermsTemplateResponse,
    TermsTemplateUpdate,
)

taxes_router = APIRouter(prefix="/taxes", tags=["Taxes"])
payment_terms_router = APIRouter(prefix="/payment-terms", tags=["Payment Terms"])
terms_templates_router = APIRouter(prefix="/terms-templates", tags=["Terms Templates"])
document_sequences_router = APIRouter(prefix="/document-sequences", tags=["Document Sequences"])
router = APIRouter()


@taxes_router.get("", response_model=ApiResponse[list[TaxResponse]])
async def list_taxes(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: TaxServiceDependency,
    filters: Annotated[TaxFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(TAX_READ))],
) -> ApiResponse[list[TaxResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        tax_category=filters.tax_category.value if filters.tax_category else None,
        is_default=filters.is_default,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


@taxes_router.post("", response_model=ApiResponse[TaxResponse], status_code=status.HTTP_201_CREATED)
async def create_tax(
    payload: TaxCreate,
    tenant: TenantContextDependency,
    service: TaxServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TAX_CREATE))],
) -> ApiResponse[TaxResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Tax created successfully")


@taxes_router.get("/{tax_id}", response_model=ApiResponse[TaxResponse])
async def get_tax(
    tax_id: UUID,
    tenant: TenantContextDependency,
    service: TaxServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TAX_READ))],
) -> ApiResponse[TaxResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, tax_id))


@taxes_router.patch("/{tax_id}", response_model=ApiResponse[TaxResponse])
async def update_tax(
    tax_id: UUID,
    payload: TaxUpdate,
    tenant: TenantContextDependency,
    service: TaxServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TAX_UPDATE))],
) -> ApiResponse[TaxResponse]:
    row = await service.update(tenant.tenant_id, tax_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Tax updated successfully")


@taxes_router.delete("/{tax_id}", response_model=ApiResponse[TaxResponse])
async def delete_tax(
    tax_id: UUID,
    tenant: TenantContextDependency,
    service: TaxServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TAX_DELETE))],
) -> ApiResponse[TaxResponse]:
    row = await service.delete(tenant.tenant_id, tax_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Tax deleted successfully")


@payment_terms_router.get("", response_model=ApiResponse[list[PaymentTermResponse]])
async def list_payment_terms(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: PaymentTermServiceDependency,
    filters: Annotated[PaymentTermFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(PAYMENT_TERM_READ))],
) -> ApiResponse[list[PaymentTermResponse]]:
    rows, total = await service.list(
        tenant.tenant_id, page=page, common_filter=filters, is_active=filters.is_active
    )
    return paginated_response(rows, params=page, total=total)


@payment_terms_router.post(
    "", response_model=ApiResponse[PaymentTermResponse], status_code=status.HTTP_201_CREATED
)
async def create_payment_term(
    payload: PaymentTermCreate,
    tenant: TenantContextDependency,
    service: PaymentTermServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PAYMENT_TERM_CREATE))],
) -> ApiResponse[PaymentTermResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Payment term created successfully")


@payment_terms_router.get("/{term_id}", response_model=ApiResponse[PaymentTermResponse])
async def get_payment_term(
    term_id: UUID,
    tenant: TenantContextDependency,
    service: PaymentTermServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PAYMENT_TERM_READ))],
) -> ApiResponse[PaymentTermResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, term_id))


@payment_terms_router.patch("/{term_id}", response_model=ApiResponse[PaymentTermResponse])
async def update_payment_term(
    term_id: UUID,
    payload: PaymentTermUpdate,
    tenant: TenantContextDependency,
    service: PaymentTermServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PAYMENT_TERM_UPDATE))],
) -> ApiResponse[PaymentTermResponse]:
    row = await service.update(tenant.tenant_id, term_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Payment term updated successfully")


@payment_terms_router.delete("/{term_id}", response_model=ApiResponse[PaymentTermResponse])
async def delete_payment_term(
    term_id: UUID,
    tenant: TenantContextDependency,
    service: PaymentTermServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(PAYMENT_TERM_DELETE))],
) -> ApiResponse[PaymentTermResponse]:
    row = await service.delete(tenant.tenant_id, term_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Payment term deleted successfully")


@terms_templates_router.get("", response_model=ApiResponse[list[TermsTemplateResponse]])
async def list_terms_templates(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: TermsTemplateServiceDependency,
    filters: Annotated[TermsTemplateFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(TERMS_TEMPLATE_READ))],
) -> ApiResponse[list[TermsTemplateResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        is_default=filters.is_default,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


@terms_templates_router.post(
    "", response_model=ApiResponse[TermsTemplateResponse], status_code=status.HTTP_201_CREATED
)
async def create_terms_template(
    payload: TermsTemplateCreate,
    tenant: TenantContextDependency,
    service: TermsTemplateServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TERMS_TEMPLATE_CREATE))],
) -> ApiResponse[TermsTemplateResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Terms template created successfully")


@terms_templates_router.get("/{template_id}", response_model=ApiResponse[TermsTemplateResponse])
async def get_terms_template(
    template_id: UUID,
    tenant: TenantContextDependency,
    service: TermsTemplateServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TERMS_TEMPLATE_READ))],
) -> ApiResponse[TermsTemplateResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, template_id))


@terms_templates_router.patch("/{template_id}", response_model=ApiResponse[TermsTemplateResponse])
async def update_terms_template(
    template_id: UUID,
    payload: TermsTemplateUpdate,
    tenant: TenantContextDependency,
    service: TermsTemplateServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TERMS_TEMPLATE_UPDATE))],
) -> ApiResponse[TermsTemplateResponse]:
    row = await service.update(tenant.tenant_id, template_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Terms template updated successfully")


@terms_templates_router.delete("/{template_id}", response_model=ApiResponse[TermsTemplateResponse])
async def delete_terms_template(
    template_id: UUID,
    tenant: TenantContextDependency,
    service: TermsTemplateServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(TERMS_TEMPLATE_DELETE))],
) -> ApiResponse[TermsTemplateResponse]:
    row = await service.delete(tenant.tenant_id, template_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Terms template deleted successfully")


@document_sequences_router.get("", response_model=ApiResponse[list[DocumentSequenceResponse]])
async def list_document_sequences(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: DocumentSequenceServiceDependency,
    filters: Annotated[DocumentSequenceFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(DOCUMENT_SEQUENCE_READ))],
) -> ApiResponse[list[DocumentSequenceResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        document_type=filters.document_type.value if filters.document_type else None,
        series=filters.series,
        fiscal_year=filters.fiscal_year,
        is_active=filters.is_active,
    )
    return paginated_response(rows, params=page, total=total)


@document_sequences_router.post(
    "",
    response_model=ApiResponse[DocumentSequenceResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_document_sequence(
    payload: DocumentSequenceCreate,
    tenant: TenantContextDependency,
    service: DocumentSequenceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DOCUMENT_SEQUENCE_CREATE))],
) -> ApiResponse[DocumentSequenceResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Document sequence created successfully")


@document_sequences_router.get(
    "/{sequence_id}", response_model=ApiResponse[DocumentSequenceResponse]
)
async def get_document_sequence(
    sequence_id: UUID,
    tenant: TenantContextDependency,
    service: DocumentSequenceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DOCUMENT_SEQUENCE_READ))],
) -> ApiResponse[DocumentSequenceResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, sequence_id))


@document_sequences_router.patch(
    "/{sequence_id}", response_model=ApiResponse[DocumentSequenceResponse]
)
async def update_document_sequence(
    sequence_id: UUID,
    payload: DocumentSequenceUpdate,
    tenant: TenantContextDependency,
    service: DocumentSequenceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DOCUMENT_SEQUENCE_UPDATE))],
) -> ApiResponse[DocumentSequenceResponse]:
    row = await service.update(tenant.tenant_id, sequence_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Document sequence updated successfully")


@document_sequences_router.delete(
    "/{sequence_id}", response_model=ApiResponse[DocumentSequenceResponse]
)
async def delete_document_sequence(
    sequence_id: UUID,
    tenant: TenantContextDependency,
    service: DocumentSequenceServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(DOCUMENT_SEQUENCE_DELETE))],
) -> ApiResponse[DocumentSequenceResponse]:
    row = await service.delete(tenant.tenant_id, sequence_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Document sequence deleted successfully")


router.include_router(taxes_router)
router.include_router(payment_terms_router)
router.include_router(terms_templates_router)
router.include_router(document_sequences_router)
