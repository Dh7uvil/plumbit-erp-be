"""Inventory management module router."""

from fastapi import APIRouter

from app.inventory_management.categories.router import router as categories_router
from app.inventory_management.price_lists.router import router as price_lists_router
from app.inventory_management.products.router import router as products_router
from app.inventory_management.stock.router import router as stock_router
from app.inventory_management.stock_adjustments.router import router as stock_adjustments_router
from app.inventory_management.stock_transfers.router import router as stock_transfers_router
from app.inventory_management.units.router import router as units_router
from app.inventory_management.warehouses.router import router as warehouses_router

router = APIRouter()
router.include_router(units_router)
router.include_router(categories_router)
router.include_router(products_router)
router.include_router(price_lists_router)
router.include_router(warehouses_router)
router.include_router(stock_router)
router.include_router(stock_transfers_router)
router.include_router(stock_adjustments_router)
