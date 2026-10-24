from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from locus.api.deps import get_current_admin_web, get_current_user_web
from locus.constants import (
    DAY_NAMES,
    DEFAULT_BELL_SCHEDULE,
    get_current_date,
)
from locus.database import get_db
from locus.models.lesson import Lesson
from locus.models.subject import Subject
from locus.models.user import User
from locus.models.vacation import Vacation
from locus.templates_config import templates

router = APIRouter(prefix="/schedule", tags=["Web Schedule"])


@router.get("", response_class=HTMLResponse)
async def schedule_page(
    request: Request,
    current_user: User = Depends(get_current_user_web),
    db: AsyncSession = Depends(get_db),
):
    today = get_current_date()
    active_day = today.isoweekday()
    if active_day > 6:
        active_day = 1

    stmt = (
        select(Lesson)
        .options(selectinload(Lesson.subject))
        .order_by(Lesson.day_of_week, Lesson.lesson_number)
    )
    res = await db.execute(stmt)
    lessons = res.scalars().all()

    schedule_by_day = {d: [] for d in range(1, 7)}
    for lesson in lessons:
        if lesson.day_of_week in schedule_by_day:
            schedule_by_day[lesson.day_of_week].append(lesson)

    subj_res = await db.execute(select(Subject).order_by(Subject.name))
    subjects = subj_res.scalars().all()

    vac_res = await db.execute(select(Vacation).order_by(Vacation.start_date.asc()))
    vacations = vac_res.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="schedule/index.html",
        context={
            "current_user": current_user,
            "active_page": "schedule",
            "active_day": active_day,
            "day_names": DAY_NAMES,
            "schedule_by_day": schedule_by_day,
            "subjects": subjects,
            "vacations": vacations,
            "default_bell_schedule": DEFAULT_BELL_SCHEDULE,
        },
    )


@router.post("")
async def create_lesson_web(
    subject_id: int = Form(...),
    day_of_week: int = Form(...),
    lesson_number: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    room: Optional[str] = Form(default=None),
    note: Optional[str] = Form(default=None),
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    subject = await db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Предмет не найден")

    lesson = Lesson(
        subject_id=subject_id,
        day_of_week=day_of_week,
        lesson_number=lesson_number,
        start_time=start_time.strip(),
        end_time=end_time.strip(),
        week_type="ALL",
        room=room.strip() if room else None,
        note=note.strip() if note else None,
    )
    db.add(lesson)
    await db.commit()

    return RedirectResponse(url="/schedule", status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/{lesson_id}")
async def delete_lesson_web(
    lesson_id: int,
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    lesson = await db.get(Lesson, lesson_id)
    if lesson:
        await db.delete(lesson)
        await db.commit()

    return Response(content="", status_code=status.HTTP_200_OK)


@router.post("/vacations")
async def create_vacation_web(
    name: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    name_clean = name.strip()
    if not name_clean:
        raise HTTPException(status_code=400, detail="Название каникул обязательно")

    try:
        s_date = date.fromisoformat(start_date.strip())
        e_date = date.fromisoformat(end_date.strip())
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Неверный формат даты")

    if s_date > e_date:
        raise HTTPException(status_code=400, detail="Дата окончания не может быть раньше даты начала")

    # Check for overlapping vacation periods
    overlap_stmt = select(Vacation).where(
        Vacation.start_date <= e_date,
        Vacation.end_date >= s_date,
    )
    overlap_res = await db.execute(overlap_stmt)
    overlap = overlap_res.scalars().first()
    if overlap:
        raise HTTPException(
            status_code=400,
            detail=f"Даты пересекаются с каникулами «{overlap.name}» ({overlap.start_date.strftime('%d.%m.%Y')}–{overlap.end_date.strftime('%d.%m.%Y')})",
        )

    vacation = Vacation(
        name=name_clean[:100],
        start_date=s_date,
        end_date=e_date,
    )
    db.add(vacation)
    await db.commit()

    return RedirectResponse(url="/schedule", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/vacations/{vacation_id}/edit")
async def edit_vacation_web(
    vacation_id: int,
    name: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    vacation = await db.get(Vacation, vacation_id)
    if not vacation:
        raise HTTPException(status_code=404, detail="Каникулы не найдены")

    name_clean = name.strip()
    if not name_clean:
        raise HTTPException(status_code=400, detail="Название каникул обязательно")

    try:
        s_date = date.fromisoformat(start_date.strip())
        e_date = date.fromisoformat(end_date.strip())
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Неверный формат даты")

    if s_date > e_date:
        raise HTTPException(status_code=400, detail="Дата окончания не может быть раньше даты начала")

    # Check for overlapping vacation periods excluding this vacation
    overlap_stmt = select(Vacation).where(
        Vacation.id != vacation_id,
        Vacation.start_date <= e_date,
        Vacation.end_date >= s_date,
    )
    overlap_res = await db.execute(overlap_stmt)
    overlap = overlap_res.scalars().first()
    if overlap:
        raise HTTPException(
            status_code=400,
            detail=f"Даты пересекаются с каникулами «{overlap.name}» ({overlap.start_date.strftime('%d.%m.%Y')}–{overlap.end_date.strftime('%d.%m.%Y')})",
        )

    vacation.name = name_clean[:100]
    vacation.start_date = s_date
    vacation.end_date = e_date
    await db.commit()

    return RedirectResponse(url="/schedule", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/vacations/{vacation_id}/edit")
async def edit_vacation_fallback(
    vacation_id: int,
    current_user: User = Depends(get_current_admin_web),
):
    return RedirectResponse(url="/schedule", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/vacations/{vacation_id}/delete")
async def delete_vacation_post(
    vacation_id: int,
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    vacation = await db.get(Vacation, vacation_id)
    if vacation:
        await db.delete(vacation)
        await db.commit()

    return RedirectResponse(url="/schedule", status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/vacations/{vacation_id}")
async def delete_vacation_web(
    vacation_id: int,
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    vacation = await db.get(Vacation, vacation_id)
    if vacation:
        await db.delete(vacation)
        await db.commit()

    return Response(content="", status_code=status.HTTP_200_OK)
