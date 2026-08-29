"""Top-level API router."""

from fastapi import APIRouter

from app.auth.router import router as auth_router
from app.common.attachments.router import router as attachments_router
from app.crm.router import router as crm_router
from app.erp.router import router as erp_router
from app.inventory_management.router import router as inventory_management_router

api_router = APIRouter(prefix="/api/v1")

# Include feature-slice routers here. Slice routers must not repeat the
# version prefix.
api_router.include_router(auth_router)
api_router.include_router(attachments_router)
api_router.include_router(crm_router)
api_router.include_router(erp_router)
api_router.include_router(inventory_management_router)
