"""Inventory management module router."""

from fastapi import APIRouter

from app.inventory_management.categories.router import router as categories_router
from app.inventory_management.units.router import router as units_router

router = APIRouter()
router.include_router(units_router)
router.include_router(categories_router)
