"""Inventory management module router."""

from fastapi import APIRouter

from app.inventory_management.units.router import router as units_router

router = APIRouter()
router.include_router(units_router)
