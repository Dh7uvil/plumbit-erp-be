"""Top-level API router."""

from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")

# Include feature-slice routers here. Slice routers must not repeat the
# version prefix.
