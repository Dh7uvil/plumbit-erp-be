"""ERP module router."""

from fastapi import APIRouter

from app.erp.accounting.router import router as accounting_router
from app.erp.exchange_rates.router import router as exchange_rates_router

router = APIRouter()
router.include_router(exchange_rates_router)
router.include_router(accounting_router)
