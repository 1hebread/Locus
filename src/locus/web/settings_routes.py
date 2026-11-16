from typing import Literal

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from locus.api.deps import get_current_user_web
from locus.constants import DEFAULT_THEME, VALID_THEMES
from locus.database import get_db
from locus.models.user import User
from locus.templates_config import templates

router = APIRouter(prefix="/settings", tags=["Web Settings"])


class ThemeUpdate(BaseModel):
    theme: Literal[*VALID_THEMES]


@router.get("", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    current_user: User = Depends(get_current_user_web),
):
    theme = current_user.theme if current_user.theme in VALID_THEMES else DEFAULT_THEME
    return templates.TemplateResponse(
        request=request,
        name="settings/index.html",
        context={
            "current_user": current_user,
            "active_page": "settings",
            "theme": theme,
        },
    )


@router.post("/theme", status_code=status.HTTP_204_NO_CONTENT)
async def update_theme(
    payload: ThemeUpdate,
    current_user: User = Depends(get_current_user_web),
    db: AsyncSession = Depends(get_db),
):
    current_user.theme = payload.theme
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
