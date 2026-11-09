from fastapi import APIRouter

from locus.api.auth import router as auth_router
from locus.api.subjects import router as subjects_router
from locus.api.schedule import router as schedule_router
from locus.api.homework import router as homework_router
from locus.api.summary import router as summary_router
from locus.api.vacations import router as vacations_router
from locus.api.duty import router as duty_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(subjects_router)
api_router.include_router(schedule_router)
api_router.include_router(homework_router)
api_router.include_router(summary_router)
api_router.include_router(vacations_router)
api_router.include_router(duty_router)

__all__ = ["api_router"]
