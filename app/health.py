"""Process liveness and dependency readiness endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter(tags=["Health"])


class HealthData(BaseModel):
    """Public health state without internal diagnostics."""

    status: Literal["healthy"] = "healthy"


class HealthResponse(BaseModel):
    """Successful health response envelope."""

    success: Literal[True] = True
    data: HealthData = Field(default_factory=HealthData)
    message: str | None = None
    meta: dict[str, object] = Field(default_factory=dict)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Check service health",
)
async def health() -> HealthResponse:
    """Report that the API process is running."""
    return HealthResponse()


@router.get(
    "/health/live",
    response_model=HealthResponse,
    summary="Check service liveness",
)
async def liveness() -> HealthResponse:
    """Report that the API process can serve requests."""
    return HealthResponse()


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "A required dependency is unavailable.",
        },
    },
    summary="Check service readiness",
)
async def readiness(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HealthResponse | JSONResponse:
    """Verify that required infrastructure is available."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "success": False,
                "error": {
                    "code": "SERVICE_UNAVAILABLE",
                    "message": "Service is not ready",
                    "details": {},
                },
            },
        )

    return HealthResponse()
