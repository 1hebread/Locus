from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from locus.api.deps import get_current_user_web
from locus.constants import HomeworkStatus, get_current_datetime
from locus.database import get_db
from locus.homework_status import attach_statuses, get_completion, set_status
from locus.lesson_suggestion import get_next_lesson_suggestion
from locus.models.homework import Homework
from locus.models.homework_completion import HomeworkCompletion
from locus.models.lesson import Lesson
from locus.models.subject import Subject
from locus.models.user import User
from locus.models.vacation import Vacation
from locus.templates_config import templates

router = APIRouter(prefix="/homework", tags=["Web Homework"])


@router.get("", response_class=HTMLResponse)
async def homework_page(
    request: Request,
    filter: Optional[str] = Query(default=None),
    open: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user_web),
    db: AsyncSession = Depends(get_db),
):
    now = get_current_datetime()
    today = now.date()

    stmt = (
        select(Homework)
        .options(selectinload(Homework.subject))
        .outerjoin(
            HomeworkCompletion,
            and_(
                HomeworkCompletion.homework_id == Homework.id,
                HomeworkCompletion.user_id == current_user.id,
            ),
        )
        .where(
            # Past-due homework is archived: keep only today and upcoming tasks
            Homework.due_date >= today,
        )
    )

    if filter == "todo":
        stmt = stmt.where(
            or_(
                HomeworkCompletion.id.is_(None),
                HomeworkCompletion.status != HomeworkStatus.DONE.value,
            )
        )
    elif filter == "done":
        stmt = stmt.where(HomeworkCompletion.status == HomeworkStatus.DONE.value)

    stmt = stmt.order_by(Homework.due_date.asc(), Homework.id.desc())
    res = await db.execute(stmt)
    homework_list = await attach_statuses(db, list(res.scalars().all()), current_user.id)

    subj_res = await db.execute(select(Subject).order_by(Subject.name))
    subjects = subj_res.scalars().all()

    lesson_res = await db.execute(
        select(Lesson)
        .options(selectinload(Lesson.subject))
        .order_by(Lesson.day_of_week, Lesson.lesson_number)
    )

    vac_res = await db.execute(
        select(Vacation)
        .where(Vacation.end_date >= today)
        .order_by(Vacation.start_date.asc())
    )
    upcoming_vacations = list(vac_res.scalars().all())

    next_lesson = get_next_lesson_suggestion(
        list(lesson_res.scalars().all()),
        now,
        vacations=upcoming_vacations,
    )

    tomorrow = today + timedelta(days=1)
    if tomorrow.isoweekday() == 7:
        default_due_date = (today + timedelta(days=2)).isoformat()
    else:
        default_due_date = tomorrow.isoformat()

    return templates.TemplateResponse(
        request=request,
        name="homework/index.html",
        context={
            "current_user": current_user,
            "active_page": "homework",
            "current_filter": filter,
            "auto_open": (open == "new"),
            "homework_list": homework_list,
            "subjects": subjects,
            "default_due_date": default_due_date,
            "next_lesson": next_lesson,
        },
    )


@router.post("")
async def create_homework_web(
    subject_id: int = Form(...),
    title: str = Form(...),
    due_date: str = Form(...),
    lesson_id: Optional[int] = Form(default=None),
    return_url: Optional[str] = Form(default=None),
    current_user: User = Depends(get_current_user_web),
    db: AsyncSession = Depends(get_db),
):
    try:
        parsed_due_date = date.fromisoformat(due_date.strip())
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Неверный формат даты")

    if parsed_due_date.isoweekday() == 7:
        raise HTTPException(
            status_code=400,
            detail="Нельзя записать домашнее задание на воскресенье",
        )

    subject = await db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Предмет не найден")

    if lesson_id:
        lesson = await db.get(Lesson, lesson_id)
        if not lesson:
            raise HTTPException(status_code=404, detail="Урок не найден")

    hw = Homework(
        subject_id=subject_id,
        lesson_id=lesson_id if lesson_id else None,
        title=title.strip(),
        due_date=parsed_due_date,
    )
    db.add(hw)
    await db.flush()
    await set_status(db, hw.id, current_user.id, HomeworkStatus.TODO.value)
    await db.commit()

    target_url = return_url if return_url and return_url.startswith("/") else "/homework"
    return RedirectResponse(url=target_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{hw_id}/toggle", response_class=HTMLResponse)
async def toggle_homework_status(
    hw_id: int,
    request: Request,
    view: Optional[str] = Query(default=None),
    prefix: Optional[str] = Query(default=None),
    day_num: Optional[int] = Query(default=None),
    current_user: User = Depends(get_current_user_web),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Homework)
        .options(selectinload(Homework.subject))
        .where(Homework.id == hw_id)
    )
    res = await db.execute(stmt)
    hw = res.scalar_one_or_none()
    if not hw:
        raise HTTPException(status_code=404, detail="Домашнее задание не найдено")

    completion = await get_completion(db, hw.id, current_user.id)
    current_status = completion.status if completion else HomeworkStatus.TODO.value
    new_status = (
        HomeworkStatus.TODO.value
        if current_status == HomeworkStatus.DONE.value
        else HomeworkStatus.DONE.value
    )
    await set_status(db, hw.id, current_user.id, new_status)
    await db.commit()
    hw.status = new_status

    if view == "compact":
        return templates.TemplateResponse(
            request=request,
            name="dashboard/hw_compact_item.html",
            context={"hw": hw, "prefix": prefix, "day_num": day_num},
        )
    if view == "unassigned":
        return templates.TemplateResponse(
            request=request,
            name="dashboard/hw_unassigned_item.html",
            context={"hw": hw, "prefix": prefix, "day_num": day_num},
        )

    return templates.TemplateResponse(
        request=request,
        name="homework/hw_item.html",
        context={"hw": hw},
    )


@router.delete("/{hw_id}")
async def delete_homework_web(
    hw_id: int,
    current_user: User = Depends(get_current_user_web),
    db: AsyncSession = Depends(get_db),
):
    hw = await db.get(Homework, hw_id)
    if hw:
        await db.delete(hw)
        await db.commit()

    return Response(content="", status_code=status.HTTP_200_OK)
