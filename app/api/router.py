from fastapi import APIRouter

from app.api.volunteer_api import router as volunteer_router
from app.api.show_admin_api import router as show_admin_router

router = APIRouter()
router.include_router(show_admin_router, prefix="/api")
router.include_router(volunteer_router, prefix="/api")
from app.api.tiles_api import router as tiles_router
router.include_router(tiles_router, prefix="/api")
