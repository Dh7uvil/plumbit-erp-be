"""CRM module router."""

from fastapi import APIRouter

from app.crm.contacts.router import router as contacts_router
from app.crm.customers.router import router as customers_router

router = APIRouter()
router.include_router(customers_router)
router.include_router(contacts_router)
