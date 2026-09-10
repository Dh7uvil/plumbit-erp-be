"""Ledger report routes."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.auth.catalog import REPORT_LEDGER, REPORT_TAX
from app.common.dependencies.auth import CurrentUser
from app.common.dependencies.permissions import require_permission
from app.common.dependencies.tenant import TenantContextDependency
from app.common.schemas.response import ApiResponse
from app.core.enums import PartyType
from app.erp.accounting.reports.dependencies import ReportServiceDependency
from app.erp.accounting.reports.schemas import (
    AccountStatementResponse,
    ExportEvidenceExceptionResponse,
    GeneralLedgerResponse,
    InvoicedNotDispatchedResponse,
    TrialBalanceResponse,
)

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/trial-balance", response_model=ApiResponse[TrialBalanceResponse])
async def get_trial_balance(
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_LEDGER))],
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    branch_id: UUID | None = None,
    include_zero: bool = False,
) -> ApiResponse[TrialBalanceResponse]:
    return ApiResponse(
        data=await service.trial_balance(
            tenant.tenant_id,
            from_date=from_date,
            to_date=to_date,
            branch_id=branch_id,
            include_zero=include_zero,
        )
    )


@router.get("/general-ledger", response_model=ApiResponse[GeneralLedgerResponse])
async def get_general_ledger(
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_LEDGER))],
    account_id: UUID,
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    party_id: UUID | None = None,
    branch_id: UUID | None = None,
) -> ApiResponse[GeneralLedgerResponse]:
    return ApiResponse(
        data=await service.general_ledger(
            tenant.tenant_id,
            account_id=account_id,
            from_date=from_date,
            to_date=to_date,
            party_id=party_id,
            branch_id=branch_id,
        )
    )


@router.get("/account-statement", response_model=ApiResponse[AccountStatementResponse])
async def get_account_statement(
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_LEDGER))],
    party_type: PartyType,
    party_id: UUID,
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
) -> ApiResponse[AccountStatementResponse]:
    return ApiResponse(
        data=await service.account_statement(
            tenant.tenant_id,
            party_type=party_type,
            party_id=party_id,
            from_date=from_date,
            to_date=to_date,
        )
    )


@router.get(
    "/export-evidence-exceptions",
    response_model=ApiResponse[ExportEvidenceExceptionResponse],
)
async def get_export_evidence_exceptions(
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_TAX))],
    as_of: date | None = None,
) -> ApiResponse[ExportEvidenceExceptionResponse]:
    return ApiResponse(
        data=await service.export_evidence_exceptions(tenant.tenant_id, as_of=as_of)
    )


@router.get(
    "/invoiced-not-dispatched",
    response_model=ApiResponse[InvoicedNotDispatchedResponse],
)
async def get_invoiced_not_dispatched(
    tenant: TenantContextDependency,
    service: ReportServiceDependency,
    _: Annotated[CurrentUser, Depends(require_permission(REPORT_TAX))],
) -> ApiResponse[InvoicedNotDispatchedResponse]:
    return ApiResponse(data=await service.invoiced_not_dispatched(tenant.tenant_id))
