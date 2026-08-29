"""CRM module router."""

from fastapi import APIRouter

from app.crm.customers.router import router as customers_router

router = APIRouter()
router.include_router(customers_router)
