"""ERP module router."""

from fastapi import APIRouter

from app.erp.exchange_rates.router import router as exchange_rates_router

router = APIRouter()
router.include_router(exchange_rates_router)
