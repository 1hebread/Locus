from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from locus.api.deps import get_current_user_web
from locus.constants import (
    DAY_NAMES,
    DAY_SHORT_NAMES,
    HomeworkStatus,
    MONTH_NAMES_GENITIVE,
    MONTH_NAMES_PREPOSITIONAL,
    calculate_break_minutes,
    format_russian_break,
    get_current_date,
    get_current_datetime,
    get_week_days_data,
    is_lesson_now,
)
from locus.database import get_db
from locus.homework_status import attach_status, attach_statuses, set_status
from locus.lesson_suggestion import get_next_lesson_suggestion
from locus.models.homework import Homework
from locus.models.lesson import Lesson
from locus.models.subject import Subject
from locus.models.user import User
from locus.models.vacation import Vacation
from locus.templates_config import templates

router = APIRouter(tags=["Dashboard"])


@router.get("/", response_class=HTMLResponse)
async def dashboard_index(
    request: Request,
    date_str: Optional[str] = Query(default=None, alias="date"),
    subgroup_param: Optional[str] = Query(default=None, alias="subgroup"),
    current_user: User = Depends(get_current_user_web),
    db: AsyncSession = Depends(get_db),
):
    today = get_current_date()

    # Admins with a subgroup default to it; "all" is an explicit opt-out.
    if subgroup_param == "all":
        active_subgroup = None
    elif subgroup_param in ("1", "2") and (current_user.is_admin or current_user.subgroup is None):
        active_subgroup = int(subgroup_param)
    else:
        active_subgroup = current_user.subgroup

    # Check for weekend lessons to decide desktop tabs and default date
    weekend_res = await db.execute(
        select(Lesson.day_of_week)
        .where(Lesson.day_of_week.in_([6, 7]))
        .distinct()
    )
    weekend_days = set(weekend_res.scalars().all())

    # Check if today falls into any vacation period
    today_vac_res = await db.execute(
        select(Vacation)
        .where(
            Vacation.start_date <= today,
            Vacation.end_date >= today,
        )
        .limit(1)
    )
    today_vacation = today_vac_res.scalars().first()

    if date_str:
        try:
            selected_date = date.fromisoformat(date_str)
        except ValueError:
            selected_date = None
    else:
        selected_date = None

    if selected_date is None:
        # Default date when not explicitly requested:
        # If today is in a vacation, stay on today to display the vacation banner.
        # Otherwise if today is weekend without lessons, advance to Sunday (if it has lessons) or next Monday.
        if today_vacation:
            selected_date = today
        else:
            dow = today.isoweekday()
            if dow == 6 and 6 not in weekend_days:
                selected_date = today + timedelta(days=1) if 7 in weekend_days else today + timedelta(days=2)
            elif dow == 7 and 7 not in weekend_days:
                selected_date = today + timedelta(days=1)
            else:
                selected_date = today

    day_weekday = selected_date.isoweekday()  # 1 = Mon .. 7 = Sun

    # Days ribbon for the week
    week_days = get_week_days_data(selected_date)
    start_monday = week_days[0]["date"]
    end_sunday = week_days[-1]["date"]
    prev_week_date = selected_date - timedelta(days=7)
    next_week_date = selected_date + timedelta(days=7)
    is_current_week = (start_monday <= today <= end_sunday)
    today_day_num = today.isoweekday()

    # Month title and week range title
    month_title = f"Расписание на {MONTH_NAMES_PREPOSITIONAL.get(selected_date.month, '')}"
    week_range_title = f"{start_monday.day} — {end_sunday.day} {MONTH_NAMES_GENITIVE.get(end_sunday.month, '')}"

    # Day title for desktop selected day
    day_name = DAY_NAMES.get(day_weekday, "")
    date_title = f"{selected_date.day} {MONTH_NAMES_GENITIVE.get(selected_date.month, '')}"
    day_title = f"{day_name} • {date_title}"
    is_today = (selected_date == today)

    # Query the shared schedule
    lesson_stmt = (
        select(Lesson)
        .options(selectinload(Lesson.subject))
        .order_by(Lesson.day_of_week, Lesson.lesson_number, Lesson.subgroup.nulls_first())
    )
    lesson_res = await db.execute(lesson_stmt)
    all_lessons = list(lesson_res.scalars().all())

    lessons_by_dow = {}
    for l in all_lessons:
        lessons_by_dow.setdefault(l.day_of_week, []).append(l)

    # Query all homework due within this week
    hw_stmt = (
        select(Homework)
        .options(selectinload(Homework.subject))
        .where(
            Homework.due_date >= start_monday,
            Homework.due_date <= end_sunday,
        )
    )
    if active_subgroup is not None:
        hw_stmt = hw_stmt.where(
            (Homework.subgroup.is_(None)) | (Homework.subgroup == active_subgroup)
        )
    hw_stmt = hw_stmt.order_by(Homework.id.asc())
    hw_res = await db.execute(hw_stmt)
    all_hw = await attach_statuses(db, list(hw_res.scalars().all()), current_user.id)

    hw_by_date = {}
    for hw in all_hw:
        if hw.due_date:
            hw_by_date.setdefault(hw.due_date, []).append(hw)

    # Query vacations overlapping this week
    vac_stmt = (
        select(Vacation)
        .where(
            Vacation.start_date <= end_sunday,
            Vacation.end_date >= start_monday,
        )
        .order_by(Vacation.start_date.asc())
    )
    vac_res = await db.execute(vac_stmt)
    week_vacations = list(vac_res.scalars().all())

    desktop_days = [
        d for d in week_days
        if d["day_num"] <= 5
        or d["day_num"] in weekend_days
        or d["is_selected"]
        or any(v.start_date <= d["date"] <= v.end_date for v in week_vacations)
        or bool(hw_by_date.get(d["date"]))
    ]

    def get_vacation_for_date(d: date) -> Optional[Vacation]:
        for v in week_vacations:
            if v.start_date <= d <= v.end_date:
                return v
        return None

    # Build days_data for all days of the week (for mobile vertical scroll)
    days_data = []
    for day in week_days:
        d_date = day["date"]
        d_num = day["day_num"]
        d_vacation = get_vacation_for_date(d_date)
        d_lessons = lessons_by_dow.get(d_num, [])

        if active_subgroup is not None:
            main_lessons = [l for l in d_lessons if l.subgroup is None or l.subgroup == active_subgroup]
        else:
            main_lessons = d_lessons

        d_hw = hw_by_date.get(d_date, [])

        lesson_hw_map = {l.id: [] for l in main_lessons}
        unassigned_hw_list = []

        if d_vacation:
            # During vacations, no regular lessons take place.
            # Put all homework due on this date into unassigned_hw_list so they are visible under the vacation banner.
            unassigned_hw_list.extend(d_hw)
        else:
            # 1. Match homework explicitly assigned to a lesson (at most 1 per lesson)
            for hw in d_hw:
                if hw.lesson_id and hw.lesson_id in lesson_hw_map and not lesson_hw_map[hw.lesson_id]:
                    lesson_hw_map[hw.lesson_id].append(hw)

            # 2. Match unassigned homework by subject and subgroup (at most 1 per lesson)
            # Match subgroup-specific homework first so generic ones don't steal their slot
            remaining_hw = [
                hw for hw in d_hw
                if not any(hw in hw_list for hw_list in lesson_hw_map.values())
            ]
            remaining_hw.sort(key=lambda h: 0 if h.subgroup is not None else 1)

            for hw in remaining_hw:
                if hw.lesson_id is not None:
                    unassigned_hw_list.append(hw)
                    continue
                matched = False
                if hw.subgroup is None:
                    # Match all parallel subgroup lessons of this subject at that slot,
                    # or the first available lesson slot.
                    target_lesson_num = None
                    for l in main_lessons:
                        if l.subject_id == hw.subject_id and not lesson_hw_map[l.id]:
                            if target_lesson_num is None:
                                target_lesson_num = l.lesson_number
                            if l.lesson_number == target_lesson_num:
                                lesson_hw_map[l.id].append(hw)
                                matched = True
                else:
                    for l in main_lessons:
                        if l.subject_id == hw.subject_id and not lesson_hw_map[l.id]:
                            if l.subgroup is None or hw.subgroup == l.subgroup:
                                lesson_hw_map[l.id].append(hw)
                                matched = True
                                break
                if not matched:
                    unassigned_hw_list.append(hw)

        day_lessons_with_meta = []
        for i, l in enumerate(main_lessons):
            break_text = None
            if i < len(main_lessons) - 1:
                next_l = main_lessons[i + 1]
                break_min = calculate_break_minutes(l.end_time, next_l.start_time)
                if break_min > 0:
                    break_text = format_russian_break(break_min)
            is_now = is_lesson_now(d_date, l.start_time, l.end_time)
            day_lessons_with_meta.append({
                "lesson": l,
                "homeworks": lesson_hw_map.get(l.id, []),
                "break_text": break_text,
                "is_now": is_now,
            })

        date_text = f"{d_date.day} {MONTH_NAMES_GENITIVE.get(d_date.month, '')}"
        day_title_text = f"{day['name']} • {date_text}"

        days_data.append({
            "day_num": d_num,
            "name": day["name"],
            "short_name": day["short_name"],
            "day_number": day["day_number"],
            "date": d_date,
            "date_iso": day["date_iso"],
            "date_text": date_text,
            "is_today": day["is_today"],
            "is_selected": day["is_selected"],
            "day_title": day_title_text,
            "lessons_with_meta": day_lessons_with_meta,
            "unassigned_hw": unassigned_hw_list,
            "has_lessons": len(day_lessons_with_meta) > 0,
            "vacation": d_vacation,
        })

    # For desktop selected day view
    selected_day_data = next((d for d in days_data if d["is_selected"]), days_data[0])
    lessons_with_meta = selected_day_data["lessons_with_meta"]
    unassigned_hw = selected_day_data["unassigned_hw"]
    active_vacation = get_vacation_for_date(selected_date)

    # Fetch subjects for quick-add modals
    subj_res = await db.execute(select(Subject).order_by(Subject.name))
    subjects = subj_res.scalars().all()
    subgroup_subjects_res = await db.execute(
        select(Lesson.subject_id).where(Lesson.subgroup.is_not(None)).distinct()
    )
    subgroup_subject_ids = set(subgroup_subjects_res.scalars().all())
    subgroup_subject_ids.update(s.id for s in subjects if s.teacher2_name and s.teacher2_name.strip())

    # Query all upcoming vacations for next lesson skipping
    all_upcoming_vac_res = await db.execute(
        select(Vacation)
        .where(Vacation.end_date >= today)
        .order_by(Vacation.start_date.asc())
    )
    upcoming_vacations = list(all_upcoming_vac_res.scalars().all())

    # The quick action is tied to the actual current lesson, so only offer it
    # while the dashboard is showing today's date. Vacations are skipped automatically.
    next_lesson = (
        get_next_lesson_suggestion(
            list(all_lessons),
            get_current_datetime(),
            vacations=upcoming_vacations,
            subgroup=active_subgroup or current_user.subgroup,
        )
        if is_today
        else None
    )

    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={
            "current_user": current_user,
            "active_page": "dashboard",
            "active_subgroup": active_subgroup,
            "month_title": month_title,
            "week_range_title": week_range_title,
            "day_title": day_title,
            "day_name": day_name,
            "date_title": date_title,
            "is_today": is_today,
            "is_current_week": is_current_week,
            "today_day_num": today_day_num,
            "selected_date": selected_date,
            "selected_date_iso": selected_date.isoformat(),
            "default_due_date": (selected_date + timedelta(days=1)).isoformat() if selected_date.isoweekday() == 7 else selected_date.isoformat(),
            "week_days": week_days,
            "desktop_days": desktop_days,
            "prev_week_date_iso": prev_week_date.isoformat(),
            "next_week_date_iso": next_week_date.isoformat(),
            "lessons_with_meta": lessons_with_meta,
            "unassigned_hw": unassigned_hw,
            "days_data": days_data,
            "subjects": subjects,
            "subgroup_subject_ids": subgroup_subject_ids,
            "next_lesson": next_lesson,
            "active_vacation": active_vacation,
        },
    )


@router.get("/dashboard/lesson/{lesson_id}/modal", response_class=HTMLResponse)
async def get_lesson_modal(
    lesson_id: int,
    request: Request,
    date_str: Optional[str] = Query(default=None, alias="date"),
    current_user: User = Depends(get_current_user_web),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Lesson)
        .options(selectinload(Lesson.subject))
        .where(Lesson.id == lesson_id)
    )
    res = await db.execute(stmt)
    lesson = res.scalar_one_or_none()
    if not lesson:
        raise HTTPException(status_code=404, detail="Урок не найден")

    if not current_user.is_admin and current_user.subgroup is not None:
        if lesson.subgroup is not None and lesson.subgroup != current_user.subgroup:
            raise HTTPException(status_code=403, detail="Доступ к уроку чужой подгруппы запрещен")

    today = get_current_date()
    if date_str:
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            target_date = today
    else:
        target_date = today

    # Fetch homework tied to this lesson (first check explicit lesson_id, then unassigned for subject)
    hw_stmt = (
        select(Homework)
        .options(selectinload(Homework.subject))
        .where(
            Homework.due_date == target_date,
            Homework.lesson_id == lesson.id,
        )
        .order_by(Homework.id.desc())
    )
    hw_res = await db.execute(hw_stmt)
    hw = hw_res.scalars().first()

    if hw and hw.subgroup is not None and not current_user.is_admin and current_user.subgroup is not None and hw.subgroup != current_user.subgroup:
        hw = None

    if not hw:
        unassigned_stmt = (
            select(Homework)
            .options(selectinload(Homework.subject))
            .where(
                Homework.due_date == target_date,
                Homework.lesson_id.is_(None),
                Homework.subject_id == lesson.subject_id,
            )
        )
        allowed_subgroup = lesson.subgroup if lesson.subgroup is not None else (
            current_user.subgroup if not current_user.is_admin else None
        )
        if allowed_subgroup is not None:
            unassigned_stmt = unassigned_stmt.where(
                (Homework.subgroup.is_(None)) | (Homework.subgroup == allowed_subgroup)
            )
        unassigned_stmt = unassigned_stmt.order_by(Homework.id.desc())
        unassigned_res = await db.execute(unassigned_stmt)
        hw = unassigned_res.scalars().first()

        if hw and hw.subgroup is not None and not current_user.is_admin and current_user.subgroup is not None and hw.subgroup != current_user.subgroup:
            hw = None

    if hw:
        await attach_status(db, hw, current_user.id)

    homeworks = [hw] if hw else []

    short_dow = DAY_SHORT_NAMES.get(target_date.isoweekday(), "")
    month_gen = MONTH_NAMES_GENITIVE.get(target_date.month, "")
    date_formatted = f"{short_dow}, {target_date.day} {month_gen}"

    return templates.TemplateResponse(
        request=request,
        name="dashboard/lesson_modal.html",
        context={
            "lesson": lesson,
            "subject": lesson.subject,
            "homeworks": homeworks,
            "hw": hw,
            "date_iso": target_date.isoformat(),
            "date_formatted": date_formatted,
            "is_sunday": (target_date.isoweekday() == 7),
        },
    )


@router.post("/dashboard/lesson/{lesson_id}/homework", response_class=HTMLResponse)
async def save_lesson_homework(
    lesson_id: int,
    request: Request,
    date_str: Optional[str] = Query(default=None, alias="date"),
    date_form: Optional[str] = Form(default=None, alias="date"),
    hw_id: Optional[int] = Form(default=None),
    hw_id_query: Optional[int] = Query(default=None, alias="hw_id"),
    title: Optional[str] = Form(default=None),
    is_done: Optional[bool] = Form(default=False),
    action: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user_web),
    db: AsyncSession = Depends(get_db),
):
    effective_hw_id = hw_id if hw_id is not None else hw_id_query
    raw_date = date_str or date_form

    stmt = (
        select(Lesson)
        .options(selectinload(Lesson.subject))
        .where(Lesson.id == lesson_id)
    )
    res = await db.execute(stmt)
    lesson = res.scalar_one_or_none()
    if not lesson:
        raise HTTPException(status_code=404, detail="Урок не найден")

    if not current_user.is_admin and current_user.subgroup is not None:
        if lesson.subgroup is not None and lesson.subgroup != current_user.subgroup:
            raise HTTPException(status_code=403, detail="Доступ к уроку чужой подгруппы запрещен")

    try:
        target_date = date.fromisoformat(raw_date) if raw_date else get_current_date()
    except ValueError:
        target_date = get_current_date()

    deleted_hw_id: Optional[int] = None
    unassigned_removed_id: Optional[int] = None
    status_val = HomeworkStatus.DONE.value if is_done else HomeworkStatus.TODO.value
    clean_title = title.strip() if title else ""

    if lesson.subgroup is not None and not current_user.is_admin and current_user.subgroup is not None and lesson.subgroup != current_user.subgroup:
        raise HTTPException(status_code=403, detail="Нельзя изменять домашнее задание для чужой подгруппы")

    hw = None
    if effective_hw_id:
        hw_stmt = select(Homework).where(Homework.id == effective_hw_id)
        hw = (await db.execute(hw_stmt)).scalar_one_or_none()
    else:
        hw_stmt = (
            select(Homework)
            .where(
                Homework.lesson_id == lesson.id,
                Homework.due_date == target_date,
            )
            .order_by(Homework.id.desc())
        )
        hw = (await db.execute(hw_stmt)).scalars().first()

    if hw and hw.subgroup is not None and not current_user.is_admin and current_user.subgroup is not None and hw.subgroup != current_user.subgroup:
        raise HTTPException(status_code=403, detail="Нельзя изменять домашнее задание чужой подгруппы")

    if action == "delete":
        if hw:
            deleted_hw_id = hw.id
            await db.delete(hw)
            await db.commit()
    elif hw:
        # If title is cleared -> delete ("пустое, значит ничего не задано")
        if not clean_title:
            deleted_hw_id = hw.id
            await db.delete(hw)
            await db.commit()
        else:
            if target_date.isoweekday() == 7:
                raise HTTPException(status_code=400, detail="Нельзя записать домашнее задание на воскресенье")
            was_unassigned = (hw.lesson_id is None)
            hw.title = clean_title
            hw.lesson_id = lesson.id
            hw.subgroup = lesson.subgroup
            await set_status(db, hw.id, current_user.id, status_val)
            if was_unassigned:
                unassigned_removed_id = hw.id
            await db.commit()
    elif clean_title:
        if target_date.isoweekday() == 7:
            raise HTTPException(status_code=400, detail="Нельзя записать домашнее задание на воскресенье")
        new_hw = Homework(
            subject_id=lesson.subject_id,
            lesson_id=lesson.id,
            title=clean_title,
            due_date=target_date,
            subgroup=lesson.subgroup,
        )
        db.add(new_hw)
        await db.flush()
        await set_status(db, new_hw.id, current_user.id, status_val)
        await db.commit()

    # Re-fetch single homework for this lesson
    hw_stmt = (
        select(Homework)
        .options(selectinload(Homework.subject))
        .where(
            Homework.due_date == target_date,
            Homework.lesson_id == lesson.id,
        )
        .order_by(Homework.id.desc())
    )
    hw_res = await db.execute(hw_stmt)
    saved_hw = hw_res.scalars().first()
    if saved_hw:
        await attach_status(db, saved_hw, current_user.id)
    updated_homeworks = [saved_hw] if saved_hw else []

    is_now = is_lesson_now(target_date, lesson.start_time, lesson.end_time)
    item = {
        "lesson": lesson,
        "homeworks": updated_homeworks,
        "is_now": is_now,
    }
    day_num = lesson.day_of_week

    return templates.TemplateResponse(
        request=request,
        name="dashboard/lesson_modal_response.html",
        context={
            "item": item,
            "lesson": lesson,
            "day": {"day_num": day_num, "date_iso": target_date.isoformat()},
            "selected_date_iso": target_date.isoformat(),
            "is_oob": True,
            "deleted_hw_id": deleted_hw_id,
            "unassigned_removed_id": unassigned_removed_id,
        },
    )
