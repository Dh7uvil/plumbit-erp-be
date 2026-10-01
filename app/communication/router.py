"""Communication module router."""

from fastapi import APIRouter

from app.communication.agora.router import router as agora_router
from app.communication.attachments.router import router as attachments_router
from app.communication.calls.router import router as calls_router
from app.communication.colleagues.router import router as colleagues_router
from app.communication.conversations.router import router as conversations_router
from app.communication.groups.router import router as groups_router
from app.communication.messages.router import router as messages_router
from app.communication.presence.router import router as presence_router
from app.communication.realtime.router import router as realtime_router
from app.communication.search.router import router as search_router
from app.communication.settings.router import router as settings_router

router = APIRouter(prefix="/communication")

router.include_router(colleagues_router)
router.include_router(conversations_router)
router.include_router(groups_router)
router.include_router(messages_router)
router.include_router(attachments_router)
router.include_router(settings_router)
router.include_router(search_router)
router.include_router(calls_router)
router.include_router(presence_router)
router.include_router(realtime_router)
router.include_router(agora_router)
