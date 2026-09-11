"""Logistics module router. Public paths stay /shipments."""

from fastapi import APIRouter

from app.logistics.shipments.router import router as shipments_router

router = APIRouter()
router.include_router(shipments_router)
