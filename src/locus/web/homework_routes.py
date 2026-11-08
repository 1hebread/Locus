from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from locus.api.deps import get_current_user_web
from locus.constants import HomeworkStatus, get_current_datetime
from locus.database import get_db
from locus.homework_audit import (
    ACTION_CREATED,
    ACTION_DELETED,
    log_homework_event,
    snapshot_changes,
)
from locus.homework_rules import LESSON_SLOT_TAKEN, lesson_homework_exists
from locus.homework_status import attach_statuses, get_completion, set_status
from locus.lesson_suggestion import get_next_lesson_suggestion
from locus.models.homework import Homework
from locus.models.homework_completion import HomeworkCompletion
from locus.models.lesson import Lesson
from locus.models.subject import Subject
from locus.models.user import User
from locus.models.vacation import Vacation
from locus.push import notify_homework_change
from locus.subgroup_helpers import build_user_subgroup_filter, user_matches_subgroup
from locus.templates_config import templates

router = APIRouter(prefix="/homework", tags=["Web Homework"])


@router.get("", response_class=HTMLResponse)
async def homework_page(
    request: Request,
    filter: Optional[str] = Query(default=None),
    open: Optional[str] = Query(default=None),
    subgroup_param: Optional[str] = Query(default=None, alias="subgroup"),
    current_user: User = Depends(get_current_user_web),
    db: AsyncSession = Depends(get_db),
):
    now = get_current_datetime()
    today = now.date()

    active_subgroup: Optional[str] = None
    if current_user.is_admin or (current_user.subgroup is None and current_user.gender_subgroup is None):
        if subgroup_param in ("1", "2", "boys", "girls"):
            active_subgroup = subgroup_param
        else:
            active_subgroup = None
    elif current_user.subgroup is not None:
        active_subgroup = str(current_user.subgroup)
    elif current_user.gender_subgroup is not None:
        active_subgroup = current_user.gender_subgroup

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

    if current_user.is_admin or (current_user.subgroup is None and current_user.gender_subgroup is None):
        if active_subgroup is not None:
            if active_subgroup in ("1", "2") and getattr(current_user, "gender_subgroup", None):
                stmt = stmt.where(
                    or_(
                        Homework.subgroup.is_(None),
                        Homework.subgroup == active_subgroup,
                        Homework.subgroup == current_user.gender_subgroup,
                    )
                )
            else:
                stmt = stmt.where(
                    or_(
                        Homework.subgroup.is_(None),
                        Homework.subgroup == active_subgroup,
                    )
                )
    else:
        user_filter = build_user_subgroup_filter(current_user, Homework.subgroup)
        if user_filter is not None:
            stmt = stmt.where(user_filter)

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

    subgroup_subjects_res = await db.execute(
        select(Lesson.subject_id).where(Lesson.subgroup.is_not(None)).distinct()
    )
    subgroup_subject_ids = set(subgroup_subjects_res.scalars().all())
    subgroup_subject_ids.update(s.id for s in subjects if s.teacher2_name and s.teacher2_name.strip())

    gender_subjects_res = await db.execute(
        select(Lesson.subject_id).where(Lesson.subgroup.in_(("boys", "girls"))).distinct()
    )
    gender_subject_ids = set(gender_subjects_res.scalars().all())

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
        subgroup=active_subgroup or current_user.subgroup,
        gender_subgroup=None if active_subgroup else current_user.gender_subgroup,
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
            "active_subgroup": active_subgroup,
            "auto_open": (open == "new"),
            "homework_list": homework_list,
            "subjects": subjects,
            "subgroup_subject_ids": subgroup_subject_ids,
            "gender_subject_ids": gender_subject_ids,
            "default_due_date": default_due_date,
            "next_lesson": next_lesson,
            "is_today": True,
        },
    )


@router.post("")
async def create_homework_web(
    background: BackgroundTasks,
    subject_id: int = Form(...),
    title: str = Form(...),
    due_date: str = Form(...),
    lesson_id: Optional[int] = Form(default=None),
    subgroup: Optional[str] = Form(default=None),
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

    resolved_subgroup: Optional[str] = None
    if subgroup is not None:
        clean_sub = subgroup.strip()
        if clean_sub in ("1", "2", "boys", "girls"):
            resolved_subgroup = clean_sub
        elif clean_sub in ("", "0", "all", "none"):
            resolved_subgroup = None
        else:
            raise HTTPException(status_code=400, detail="Неверная подгруппа")
    elif lesson_id is None and not current_user.is_admin:
        gender_lesson = await db.execute(
            select(Lesson.id).where(
                Lesson.subject_id == subject.id,
                Lesson.subgroup.in_(("boys", "girls")),
            ).limit(1)
        )
        if gender_lesson.scalar_one_or_none() is not None:
            resolved_subgroup = current_user.gender_subgroup
        else:
            resolved_subgroup = str(current_user.subgroup) if current_user.subgroup is not None else current_user.gender_subgroup

    lesson = None
    if lesson_id:
        lesson = await db.get(Lesson, lesson_id)
        if not lesson:
            raise HTTPException(status_code=404, detail="Урок не найден")
        if resolved_subgroup is not None and lesson.subgroup is not None and str(resolved_subgroup) != str(lesson.subgroup):
            raise HTTPException(status_code=400, detail="Подгруппа задания не совпадает с подгруппой урока")
        if subgroup is None and lesson.subgroup is not None:
            resolved_subgroup = lesson.subgroup

    if not user_matches_subgroup(current_user, resolved_subgroup):
        raise HTTPException(
            status_code=403,
            detail="Нельзя создать задание для чужой подгруппы",
        )
    if lesson and not user_matches_subgroup(current_user, lesson.subgroup):
        raise HTTPException(
            status_code=403,
            detail="Нельзя привязать задание к уроку чужой подгруппы",
        )
    if lesson is not None and await lesson_homework_exists(db, lesson.id, parsed_due_date):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=LESSON_SLOT_TAKEN,
        )

    if resolved_subgroup is not None:
        has_subgroups = bool(subject.teacher2_name and subject.teacher2_name.strip())
        if not has_subgroups:
            sub_lesson = await db.execute(
                select(Lesson.id).where(Lesson.subject_id == subject.id, Lesson.subgroup.is_not(None)).limit(1)
            )
            has_subgroups = sub_lesson.scalar_one_or_none() is not None
        if not has_subgroups:
            resolved_subgroup = None

    hw = Homework(
        subject_id=subject_id,
        lesson_id=lesson_id if lesson_id else None,
        title=title.strip(),
        due_date=parsed_due_date,
        subgroup=resolved_subgroup,
    )
    db.add(hw)
    try:
        await db.flush()
    except IntegrityError:
        # Unique index (lesson_id, due_date) caught a concurrent duplicate.
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=LESSON_SLOT_TAKEN)
    await set_status(db, hw.id, current_user.id, HomeworkStatus.TODO.value)
    log_homework_event(db, current_user, ACTION_CREATED, hw.id, snapshot_changes(hw))
    await db.commit()
    notify_homework_change(
        background, current_user, ACTION_CREATED, hw.id, hw.title, subject.name, hw.subgroup, hw.due_date
    )

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

    if not user_matches_subgroup(current_user, hw.subgroup):
        raise HTTPException(status_code=403, detail="Нельзя менять статус задания чужой подгруппы")

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
    background: BackgroundTasks,
    current_user: User = Depends(get_current_user_web),
    db: AsyncSession = Depends(get_db),
):
    hw = await db.get(Homework, hw_id)
    if hw:
        if not user_matches_subgroup(current_user, hw.subgroup):
            raise HTTPException(status_code=403, detail="Нельзя удалить задание чужой подгруппы")
        subject = await db.get(Subject, hw.subject_id)
        notify_homework_change(
            background, current_user, ACTION_DELETED, hw.id, hw.title, subject.name if subject else "", hw.subgroup, hw.due_date
        )
        log_homework_event(
            db, current_user, ACTION_DELETED, None, snapshot_changes(hw, deleted=True)
        )
        await db.delete(hw)
        await db.commit()

    return Response(content="", status_code=status.HTTP_200_OK)
