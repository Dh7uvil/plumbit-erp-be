"""CRM module router."""

from fastapi import APIRouter

from app.crm.activities.router import router as activities_router
from app.crm.campaigns.router import router as campaigns_router
from app.crm.contacts.router import router as contacts_router
from app.crm.customers.router import router as customers_router
from app.crm.lead_sources.router import router as lead_sources_router
from app.crm.leads.router import router as leads_router
from app.crm.lost_reasons.router import router as lost_reasons_router
from app.crm.notes.router import router as notes_router
from app.crm.opportunities.router import router as opportunities_router
from app.crm.pipelines.router import router as pipelines_router

router = APIRouter()
router.include_router(customers_router)
router.include_router(contacts_router)
router.include_router(pipelines_router)
router.include_router(lead_sources_router)
router.include_router(lost_reasons_router)
router.include_router(leads_router)
router.include_router(opportunities_router)
router.include_router(activities_router)
router.include_router(notes_router)
router.include_router(campaigns_router)
