"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.error_handlers import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import engine
from app.health import router as health_router
from app.router import api_router

OPENAPI_TAGS: list[dict[str, str]] = [
    {
        "name": "Health",
        "description": "Process liveness and dependency readiness probes.",
    },
    {
        "name": "Tenants",
        "description": "Public tenant discovery and the current organization's settings.",
    },
    {
        "name": "Auth",
        "description": "Authentication, session rotation, and the current-user profile.",
    },
    {
        "name": "Users",
        "description": "Tenant user management, role assignment, and nested employee profiles.",
    },
    {
        "name": "Roles",
        "description": "Role management and permission assignment.",
    },
    {
        "name": "Permissions",
        "description": "Permission catalog (`identity.<resource>.<action>`) and the role matrix.",
    },
    {
        "name": "Branches",
        "description": "Tenant operating locations.",
    },
    {
        "name": "Departments",
        "description": "Departments belonging to a branch.",
    },
    {
        "name": "Audit Logs",
        "description": "Append-only audit trail for identity and organization changes.",
    },
    {
        "name": "Attachments",
        "description": "Generic document uploads stored in MinIO locally and S3 in production.",
    },
    {
        "name": "Currencies",
        "description": "Tenant currency master including the AED base.",
    },
    {
        "name": "Exchange Rates",
        "description": "Org-level daily user-entered rates versus the base currency.",
    },
    {
        "name": "Taxes",
        "description": "UAE VAT tax master with a single default rate per tenant.",
    },
    {
        "name": "Payment Terms",
        "description": "Named payment terms copied onto commercial documents.",
    },
    {
        "name": "Terms Templates",
        "description": "Reusable terms-and-conditions bodies for quotations.",
    },
    {
        "name": "Document Sequences",
        "description": "Locked counters that allocate human-readable document numbers.",
    },
    {
        "name": "Units",
        "description": "Unit of measure master used on products and quote lines.",
    },
    {
        "name": "Categories",
        "description": "Hierarchical product category master.",
    },
    {
        "name": "Products",
        "description": "Sellable goods and services master used on quotations.",
    },
    {
        "name": "Price Lists",
        "description": "Customer-assignable rate charts used on quotations.",
    },
]
APP_DESCRIPTION = "Multi-tenant ERP backend API."


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Own application-level resources for the process lifetime."""
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    """Create and configure a FastAPI application instance."""
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title=settings.app_name,
        description=APP_DESCRIPTION,
        version=settings.app_version,
        lifespan=lifespan,
        openapi_tags=OPENAPI_TAGS,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin).rstrip("/") for origin in settings.cors_origins],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestContextMiddleware)

    register_error_handlers(application)
    application.include_router(health_router)
    application.include_router(api_router)
    return application


app = create_app()
