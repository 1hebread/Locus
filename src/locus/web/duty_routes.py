from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from locus.api.deps import get_current_admin_web, get_current_user_web
from locus.database import get_db
from locus.duty import load_duty_days, set_duty_text
from locus.models.user import User
from locus.templates_config import templates

router = APIRouter(prefix="/duty", tags=["Web Duty"])


@router.get("", response_class=HTMLResponse)
async def duty_page(
    request: Request,
    current_user: User = Depends(get_current_user_web),
    db: AsyncSession = Depends(get_db),
):
    return templates.TemplateResponse(
        request=request,
        name="duty/index.html",
        context={
            "current_user": current_user,
            "active_page": "duty",
            "days": await load_duty_days(db, current_user),
        },
    )


@router.post("")
async def save_duty(
    request: Request,
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    for day_num in range(1, 7):
        text = str(form.get(f"day_{day_num}", "") or "").strip()
        await set_duty_text(db, day_num, text)
    await db.commit()

    return RedirectResponse(url="/duty", status_code=status.HTTP_303_SEE_OTHER)
