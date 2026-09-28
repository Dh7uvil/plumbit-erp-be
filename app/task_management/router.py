"""Task management module router."""

from fastapi import APIRouter

from app.task_management.task_labels.router import router as task_labels_router
from app.task_management.tasks.router import router as tasks_router

router = APIRouter()
router.include_router(tasks_router)
router.include_router(task_labels_router)
