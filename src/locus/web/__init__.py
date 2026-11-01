from fastapi import APIRouter

from locus.web.auth_routes import router as auth_web_router
from locus.web.admin_routes import router as admin_web_router
from locus.web.dashboard_routes import router as dashboard_web_router
from locus.web.schedule_routes import router as schedule_web_router
from locus.web.homework_routes import router as homework_web_router
from locus.web.push_routes import router as push_web_router
from locus.web.subjects_routes import router as subjects_web_router

web_router = APIRouter()
web_router.include_router(auth_web_router)
web_router.include_router(admin_web_router)
web_router.include_router(dashboard_web_router)
web_router.include_router(schedule_web_router)
web_router.include_router(homework_web_router)
web_router.include_router(push_web_router)
web_router.include_router(subjects_web_router)

__all__ = ["web_router"]
