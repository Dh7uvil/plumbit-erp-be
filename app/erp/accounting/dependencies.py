"""Accounting slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.erp.accounting.service import (
    DocumentSequenceService,
    PaymentTermService,
    TaxService,
    TermsTemplateService,
)


def get_tax_service(session: Annotated[AsyncSession, Depends(get_db)]) -> TaxService:
    return TaxService(session)


def get_payment_term_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PaymentTermService:
    return PaymentTermService(session)


def get_terms_template_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TermsTemplateService:
    return TermsTemplateService(session)


def get_document_sequence_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentSequenceService:
    return DocumentSequenceService(session)


TaxServiceDependency = Annotated[TaxService, Depends(get_tax_service)]
PaymentTermServiceDependency = Annotated[PaymentTermService, Depends(get_payment_term_service)]
TermsTemplateServiceDependency = Annotated[
    TermsTemplateService, Depends(get_terms_template_service)
]
DocumentSequenceServiceDependency = Annotated[
    DocumentSequenceService, Depends(get_document_sequence_service)
]
