from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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
from locus.models.homework import Homework
from locus.models.lesson import Lesson
from locus.models.subject import Subject
from locus.models.user import User
from locus.models.vacation import Vacation
from locus.schedule_service import LessonNotFoundError, clone_lesson_record
from locus.schedule_validation import LessonConflictError, validate_lesson_conflict
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
        .order_by(Lesson.day_of_week, Lesson.lesson_number, Lesson.subgroup.nulls_first())
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

    schedule_data = {
        d: [
            {
                "id": l.id,
                "lesson_number": l.lesson_number,
                "start_time": l.start_time,
                "end_time": l.end_time,
                "week_type": l.week_type,
                "subgroup": l.subgroup,
                "subject_id": l.subject_id,
                "subject_name": l.subject.name if l.subject else "Урок",
                "room": l.room or "",
                "note": l.note or "",
            }
            for l in schedule_by_day[d]
        ]
        for d in range(1, 7)
    }

    return templates.TemplateResponse(
        request=request,
        name="schedule/index.html",
        context={
            "current_user": current_user,
            "active_page": "schedule",
            "active_day": active_day,
            "day_names": DAY_NAMES,
            "schedule_by_day": schedule_by_day,
            "schedule_data": schedule_data,
            "subjects": subjects,
            "vacations": vacations,
            "default_bell_schedule": DEFAULT_BELL_SCHEDULE,
        },
    )


async def _get_day_lessons(db: AsyncSession, day_of_week: int) -> list[Lesson]:
    stmt = (
        select(Lesson)
        .where(Lesson.day_of_week == day_of_week)
        .options(selectinload(Lesson.subject))
        .order_by(Lesson.lesson_number, Lesson.subgroup.nulls_first())
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


def _serialize_lessons_data(lessons: list[Lesson]) -> list[dict]:
    return [
        {
            "id": l.id,
            "lesson_number": l.lesson_number,
            "start_time": l.start_time,
            "end_time": l.end_time,
            "week_type": l.week_type,
            "subgroup": l.subgroup,
            "subject_id": l.subject_id,
            "subject_name": l.subject.name if l.subject else "Урок",
            "room": l.room or "",
            "note": l.note or "",
        }
        for l in lessons
    ]


def _render_day_lessons_html(
    request: Request,
    day_of_week: int,
    lessons: list[Lesson],
    current_user: User,
) -> str:
    template = templates.get_template("schedule/day_lessons.html")
    return template.render(
        request=request,
        schedule_by_day={day_of_week: lessons},
        d_num=day_of_week,
        current_user=current_user,
    )


@router.post("")
async def create_lesson_web(
    request: Request,
    subject_id: int = Form(...),
    day_of_week: int = Form(...),
    lesson_number: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    subgroup: Optional[int] = Form(default=None),
    room: Optional[str] = Form(default=None),
    note: Optional[str] = Form(default=None),
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    if day_of_week < 1 or day_of_week > 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="День недели должен быть от 1 до 6")
    if lesson_number < 1 or lesson_number > 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Номер урока должен быть от 1 до 8")
    if subgroup is not None and subgroup not in (1, 2):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Номер подгруппы должен быть 1 или 2")

    subject = await db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Предмет не найден")

    clean_start = start_time.strip()
    clean_end = end_time.strip()

    try:
        await validate_lesson_conflict(
            db=db,
            day_of_week=day_of_week,
            lesson_number=lesson_number,
            start_time=clean_start,
            end_time=clean_end,
            week_type="ALL",
            subgroup=subgroup,
        )
    except LessonConflictError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    clean_room = room.strip()[:50] if room and room.strip() else None
    clean_note = note.strip()[:255] if note and note.strip() else None

    lesson = Lesson(
        subject_id=subject_id,
        day_of_week=day_of_week,
        lesson_number=lesson_number,
        start_time=clean_start,
        end_time=clean_end,
        week_type="ALL",
        subgroup=subgroup,
        room=clean_room,
        note=clean_note,
    )
    db.add(lesson)
    await db.commit()

    if "application/json" in request.headers.get("accept", ""):
        day_lessons = await _get_day_lessons(db, lesson.day_of_week)
        day_html = _render_day_lessons_html(request, lesson.day_of_week, day_lessons, current_user)
        return JSONResponse({
            "ok": True,
            "redirect": "/schedule",
            "days": {
                str(lesson.day_of_week): {
                    "html": day_html,
                    "count": len(day_lessons),
                    "schedule_data": _serialize_lessons_data(day_lessons),
                }
            },
        })
    return RedirectResponse(url="/schedule", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{lesson_id}/edit")
async def edit_lesson_web_get(
    lesson_id: int,
    current_user: User = Depends(get_current_admin_web),
):
    return RedirectResponse(url="/schedule", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{lesson_id}/edit")
async def edit_lesson_web(
    request: Request,
    lesson_id: int,
    subject_id: int = Form(...),
    day_of_week: int = Form(...),
    lesson_number: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    subgroup: Optional[int] = Form(default=None),
    room: Optional[str] = Form(default=None),
    note: Optional[str] = Form(default=None),
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    lesson = await db.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="Урок не найден")

    if day_of_week < 1 or day_of_week > 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="День недели должен быть от 1 до 6")
    if lesson_number < 1 or lesson_number > 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Номер урока должен быть от 1 до 8")
    if subgroup is not None and subgroup not in (1, 2):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Номер подгруппы должен быть 1 или 2")

    subject = await db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Предмет не найден")

    clean_start = start_time.strip()
    clean_end = end_time.strip()

    try:
        await validate_lesson_conflict(
            db=db,
            day_of_week=day_of_week,
            lesson_number=lesson_number,
            start_time=clean_start,
            end_time=clean_end,
            week_type=lesson.week_type,
            subgroup=subgroup,
            exclude_lesson_id=lesson.id,
        )
    except LessonConflictError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    clean_room = room.strip()[:50] if room and room.strip() else None
    clean_note = note.strip()[:255] if note and note.strip() else None

    subject_changed = (lesson.subject_id != subject_id)
    old_day = lesson.day_of_week
    day_changed = (old_day != day_of_week)

    lesson.subject_id = subject_id
    lesson.day_of_week = day_of_week
    lesson.lesson_number = lesson_number
    lesson.start_time = clean_start
    lesson.end_time = clean_end
    lesson.subgroup = subgroup
    lesson.room = clean_room
    lesson.note = clean_note

    # Update or unbind any homework assigned directly to this lesson
    hw_stmt = select(Homework).where(Homework.lesson_id == lesson.id)
    hw_res = await db.execute(hw_stmt)
    for hw in hw_res.scalars().all():
        if subject_changed or day_changed:
            hw.lesson_id = None
        else:
            hw.subgroup = subgroup

    await db.commit()

    if "application/json" in request.headers.get("accept", ""):
        days_to_update = {lesson.day_of_week}
        if day_changed:
            days_to_update.add(old_day)
        days_payload = {}
        for d in days_to_update:
            d_lessons = await _get_day_lessons(db, d)
            days_payload[str(d)] = {
                "html": _render_day_lessons_html(request, d, d_lessons, current_user),
                "count": len(d_lessons),
                "schedule_data": _serialize_lessons_data(d_lessons),
            }
        return JSONResponse({
            "ok": True,
            "redirect": "/schedule",
            "days": days_payload,
        })
    return RedirectResponse(url="/schedule", status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/{lesson_id}")
async def delete_lesson_web(
    request: Request,
    lesson_id: int,
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    lesson = await db.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Урок не найден")

    affected_day = lesson.day_of_week
    await db.delete(lesson)
    await db.commit()

    if "application/json" in request.headers.get("accept", ""):
        d_lessons = await _get_day_lessons(db, affected_day)
        return JSONResponse({
            "ok": True,
            "redirect": "/schedule",
            "days": {
                str(affected_day): {
                    "html": _render_day_lessons_html(request, affected_day, d_lessons, current_user),
                    "count": len(d_lessons),
                    "schedule_data": _serialize_lessons_data(d_lessons),
                }
            },
        })

    return Response(content="", status_code=status.HTTP_200_OK)


@router.post("/{lesson_id}/clone")
async def clone_lesson_web(
    request: Request,
    lesson_id: int,
    current_user: User = Depends(get_current_admin_web),
    db: AsyncSession = Depends(get_db),
):
    try:
        cloned_lesson = await clone_lesson_record(db, lesson_id)
    except LessonNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Урок не найден")
    except LessonConflictError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if "application/json" in request.headers.get("accept", ""):
        d_lessons = await _get_day_lessons(db, cloned_lesson.day_of_week)
        return JSONResponse({
            "ok": True,
            "redirect": "/schedule",
            "days": {
                str(cloned_lesson.day_of_week): {
                    "html": _render_day_lessons_html(request, cloned_lesson.day_of_week, d_lessons, current_user),
                    "count": len(d_lessons),
                    "schedule_data": _serialize_lessons_data(d_lessons),
                }
            },
        })
    return RedirectResponse(url="/schedule", status_code=status.HTTP_303_SEE_OTHER)


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
