"""ERP module router."""

from fastapi import APIRouter

from app.erp.accounting.router import router as accounting_router
from app.erp.exchange_rates.router import router as exchange_rates_router
from app.erp.quotation.router import router as quotation_router
from app.erp.suppliers.router import router as suppliers_router

router = APIRouter()
router.include_router(exchange_rates_router)
router.include_router(accounting_router)
router.include_router(suppliers_router)
router.include_router(quotation_router)
