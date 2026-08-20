"""Top-level API router."""

from fastapi import APIRouter

from app.auth.router import router as auth_router

api_router = APIRouter(prefix="/api/v1")

# Include feature-slice routers here. Slice routers must not repeat the
# version prefix.
api_router.include_router(auth_router)
