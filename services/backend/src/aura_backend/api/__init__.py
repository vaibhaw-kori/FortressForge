"""REST API v1 routers."""

from fastapi import APIRouter

from .v1.admin import router as admin_router
from .v1.captures import router as captures_router
from .v1.experiences import router as experiences_router
from .v1.generation import router as generation_router
from .v1.health import router as health_router
from .v1.sessions import router as sessions_router
from .v1.storage import router as storage_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health_router)
api_v1_router.include_router(sessions_router)
api_v1_router.include_router(captures_router)
api_v1_router.include_router(experiences_router)
api_v1_router.include_router(generation_router)
api_v1_router.include_router(storage_router)
api_v1_router.include_router(admin_router)

__all__ = ["api_v1_router"]