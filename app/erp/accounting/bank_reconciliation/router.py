"""Bank reconciliation routes."""

from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile, status

from app.auth.catalog import (
    BANK_RECONCILIATION_CREATE,
    BANK_RECONCILIATION_DELETE,
    BANK_RECONCILIATION_EXPORT,
    BANK_RECONCILIATION_IMPORT,
    BANK_RECONCILIATION_READ,
    BANK_RECONCILIATION_RECONCILE,
    BANK_RECONCILIATION_UPDATE,
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
from app.common.utils.concurrency import require_document_version
from app.erp.accounting.bank_reconciliation.dependencies import BankReconciliationServiceDependency
from app.erp.accounting.bank_reconciliation.schemas import (
    BankStatementCreate,
    BankStatementFilter,
    BankStatementResponse,
    BankStatementUpdate,
    BookEntryCandidate,
    ExcludeLineRequest,
    MatchRequest,
    MatchSuggestion,
    ReconciliationStatement,
    UnmatchRequest,
)

router = APIRouter(prefix="/bank-reconciliation", tags=["Bank Reconciliation"])

IfMatch = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=ApiResponse[list[BankStatementResponse]])
async def list_bank_statements(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: BankReconciliationServiceDependency,
    filters: Annotated[BankStatementFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(BANK_RECONCILIATION_READ))],
) -> ApiResponse[list[BankStatementResponse]]:
    rows, total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        bank_account_id=filters.bank_account_id,
        status=filters.status.value if filters.status else None,
    )
    return paginated_response(rows, params=page, total=total)


@router.post(
    "",
    response_model=ApiResponse[BankStatementResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_bank_statement(
    payload: BankStatementCreate,
    tenant: TenantContextDependency,
    service: BankReconciliationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BANK_RECONCILIATION_CREATE))],
) -> ApiResponse[BankStatementResponse]:
    row = await service.create(tenant.tenant_id, payload, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Bank statement created successfully")


@router.get("/export")
async def bank_reconciliation_export(
    tenant: TenantContextDependency,
    page: PaginationDependency,
    service: BankReconciliationServiceDependency,
    filters: Annotated[BankStatementFilter, Depends()],
    _: Annotated[CurrentUser, Depends(require_permission(BANK_RECONCILIATION_EXPORT))],
) -> object:
    rows, _total = await service.list(
        tenant.tenant_id,
        page=page,
        common_filter=filters,
        bank_account_id=filters.bank_account_id,
        status=filters.status.value if filters.status else None,
    )
    return export_response(
        "bank-reconciliation",
        [
            "period_start",
            "period_end",
            "status",
            "opening_balance",
            "closing_balance",
            "import_reference",
            "line_count",
        ],
        [
            [
                row.period_start,
                row.period_end,
                row.status.value,
                row.opening_balance,
                row.closing_balance,
                row.import_reference or "",
                len(row.lines),
            ]
            for row in rows
        ],
    )


@router.get("/import/template")
async def bank_statement_import_template(
    _: Annotated[CurrentUser, Depends(require_permission(BANK_RECONCILIATION_IMPORT))],
) -> object:
    return template_response("bank_statement")


@router.post("/import/preview", response_model=ApiResponse[ImportPreviewResponse])
async def bank_statement_import_preview(
    _: Annotated[CurrentUser, Depends(require_permission(BANK_RECONCILIATION_IMPORT))],
    file: Annotated[UploadFile, File()],
) -> ApiResponse[ImportPreviewResponse]:
    filename, content = await read_upload(file)
    return ApiResponse(data=preview_file("bank_statement", filename=filename, content=content))


@router.post(
    "/import",
    response_model=ApiResponse[ImportResult],
    status_code=status.HTTP_201_CREATED,
)
async def bank_statement_import(
    tenant: TenantContextDependency,
    service: BankReconciliationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BANK_RECONCILIATION_IMPORT))],
    file: Annotated[UploadFile, File()],
    bank_account_id: Annotated[UUID, Form()],
    period_start: Annotated[date, Form()],
    period_end: Annotated[date, Form()],
    opening_balance: Annotated[Decimal, Form()],
    closing_balance: Annotated[Decimal, Form()],
    mapping: Annotated[str | None, Form()] = None,
    idempotency_key: IdempotencyKeyHeader = None,
) -> ApiResponse[ImportResult]:
    require_idempotency_key(idempotency_key)
    filename, content = await read_upload(file)
    result = await service.import_rows(
        tenant.tenant_id,
        bank_account_id=bank_account_id,
        period_start=period_start,
        period_end=period_end,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        filename=filename,
        content=content,
        mapping=parse_mapping_json(mapping),
        actor_user_id=tenant.user_id,
    )
    return ApiResponse(data=result, message="Bank statement imported")


@router.get("/{statement_id}", response_model=ApiResponse[BankStatementResponse])
async def get_bank_statement(
    statement_id: UUID,
    tenant: TenantContextDependency,
    service: BankReconciliationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BANK_RECONCILIATION_READ))],
) -> ApiResponse[BankStatementResponse]:
    return ApiResponse(data=await service.get(tenant.tenant_id, statement_id))


@router.patch("/{statement_id}", response_model=ApiResponse[BankStatementResponse])
async def update_bank_statement(
    statement_id: UUID,
    payload: BankStatementUpdate,
    tenant: TenantContextDependency,
    service: BankReconciliationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BANK_RECONCILIATION_UPDATE))],
    if_match: IfMatch = None,
) -> ApiResponse[BankStatementResponse]:
    version = require_document_version(if_match=if_match, body_version=payload.version)
    row = await service.update(
        tenant.tenant_id,
        statement_id,
        payload,
        actor_user_id=tenant.user_id,
        expected_version=version,
    )
    return ApiResponse(data=row, message="Bank statement updated successfully")


@router.delete("/{statement_id}", response_model=ApiResponse[BankStatementResponse])
async def delete_bank_statement(
    statement_id: UUID,
    tenant: TenantContextDependency,
    service: BankReconciliationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BANK_RECONCILIATION_DELETE))],
) -> ApiResponse[BankStatementResponse]:
    row = await service.delete(tenant.tenant_id, statement_id, actor_user_id=tenant.user_id)
    return ApiResponse(data=row, message="Bank statement deleted successfully")


@router.get(
    "/{statement_id}/book-entries",
    response_model=ApiResponse[list[BookEntryCandidate]],
)
async def list_book_entries(
    statement_id: UUID,
    tenant: TenantContextDependency,
    service: BankReconciliationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BANK_RECONCILIATION_READ))],
) -> ApiResponse[list[BookEntryCandidate]]:
    rows = await service.book_entries(tenant.tenant_id, statement_id)
    return ApiResponse(data=rows)


@router.get(
    "/{statement_id}/suggested-matches",
    response_model=ApiResponse[list[MatchSuggestion]],
)
async def list_suggested_matches(
    statement_id: UUID,
    tenant: TenantContextDependency,
    service: BankReconciliationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BANK_RECONCILIATION_READ))],
) -> ApiResponse[list[MatchSuggestion]]:
    rows = await service.suggest_matches(tenant.tenant_id, statement_id)
    return ApiResponse(data=rows)


@router.get(
    "/{statement_id}/reconciliation-statement",
    response_model=ApiResponse[ReconciliationStatement],
)
async def get_reconciliation_statement(
    statement_id: UUID,
    tenant: TenantContextDependency,
    service: BankReconciliationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BANK_RECONCILIATION_READ))],
) -> ApiResponse[ReconciliationStatement]:
    return ApiResponse(data=await service.reconciliation_statement(tenant.tenant_id, statement_id))


@router.post("/{statement_id}/match", response_model=ApiResponse[BankStatementResponse])
async def match_statement_line(
    statement_id: UUID,
    payload: MatchRequest,
    tenant: TenantContextDependency,
    service: BankReconciliationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BANK_RECONCILIATION_RECONCILE))],
    if_match: IfMatch = None,
) -> ApiResponse[BankStatementResponse]:
    version = require_document_version(if_match=if_match, body_version=payload.version)
    row = await service.match(
        tenant.tenant_id,
        statement_id,
        statement_line_id=payload.statement_line_id,
        journal_line_id=payload.journal_line_id,
        actor_user_id=tenant.user_id,
        expected_version=version,
    )
    return ApiResponse(data=row, message="Statement line matched")


@router.post("/{statement_id}/unmatch", response_model=ApiResponse[BankStatementResponse])
async def unmatch_statement_line(
    statement_id: UUID,
    payload: UnmatchRequest,
    tenant: TenantContextDependency,
    service: BankReconciliationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BANK_RECONCILIATION_RECONCILE))],
    if_match: IfMatch = None,
) -> ApiResponse[BankStatementResponse]:
    version = require_document_version(if_match=if_match, body_version=payload.version)
    row = await service.unmatch(
        tenant.tenant_id,
        statement_id,
        statement_line_id=payload.statement_line_id,
        actor_user_id=tenant.user_id,
        expected_version=version,
    )
    return ApiResponse(data=row, message="Statement line unmatched")


@router.post("/{statement_id}/exclude", response_model=ApiResponse[BankStatementResponse])
async def exclude_statement_line(
    statement_id: UUID,
    payload: ExcludeLineRequest,
    tenant: TenantContextDependency,
    service: BankReconciliationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BANK_RECONCILIATION_RECONCILE))],
    if_match: IfMatch = None,
) -> ApiResponse[BankStatementResponse]:
    version = require_document_version(if_match=if_match, body_version=payload.version)
    row = await service.exclude_line(
        tenant.tenant_id,
        statement_id,
        statement_line_id=payload.statement_line_id,
        actor_user_id=tenant.user_id,
        expected_version=version,
    )
    return ApiResponse(data=row, message="Statement line excluded")


@router.post("/{statement_id}/reconcile", response_model=ApiResponse[BankStatementResponse])
async def reconcile_statement(
    statement_id: UUID,
    tenant: TenantContextDependency,
    service: BankReconciliationServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(BANK_RECONCILIATION_RECONCILE))],
    if_match: IfMatch = None,
    version: int | None = None,
) -> ApiResponse[BankStatementResponse]:
    expected = require_document_version(if_match=if_match, body_version=version)
    row = await service.reconcile(
        tenant.tenant_id,
        statement_id,
        actor_user_id=tenant.user_id,
        expected_version=expected,
    )
    return ApiResponse(data=row, message="Bank statement reconciled")
