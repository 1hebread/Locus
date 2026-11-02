from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from locus.api.deps import get_current_user
from locus.constants import DAY_NAMES, get_current_date
from locus.database import get_db
from locus.homework_status import attach_statuses
from locus.models.homework import Homework
from locus.models.lesson import Lesson
from locus.models.user import User
from locus.models.vacation import Vacation
from locus.schemas.summary import DaySummary, SummaryLesson
from locus.subgroup_helpers import build_user_subgroup_filter

router = APIRouter(prefix="/summary", tags=["Summary"])


@router.get("", response_model=DaySummary)
async def day_summary(
    target_date: Optional[date] = Query(default=None, alias="date"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lessons and homework for a single day (today by default)."""
    target = target_date or get_current_date()
    day_of_week = target.isoweekday()

    vacation = (
        await db.execute(
            select(Vacation)
            .where(Vacation.start_date <= target, Vacation.end_date >= target)
            .order_by(Vacation.start_date)
            .limit(1)
        )
    ).scalars().first()

    lesson_stmt = (
        select(Lesson)
        .options(selectinload(Lesson.subject))
        .where(Lesson.day_of_week == day_of_week)
        .order_by(Lesson.lesson_number, Lesson.subgroup.nulls_first())
    )
    user_lesson_filter = build_user_subgroup_filter(current_user, Lesson.subgroup)
    if user_lesson_filter is not None:
        lesson_stmt = lesson_stmt.where(user_lesson_filter)
    lessons = list((await db.execute(lesson_stmt)).scalars().all())

    hw_stmt = (
        select(Homework)
        .options(selectinload(Homework.subject))
        .where(Homework.due_date == target)
        .order_by(Homework.id)
    )
    user_hw_filter = build_user_subgroup_filter(current_user, Homework.subgroup)
    if user_hw_filter is not None:
        hw_stmt = hw_stmt.where(user_hw_filter)
    homeworks = await attach_statuses(
        db, list((await db.execute(hw_stmt)).scalars().all()), current_user.id
    )

    # No regular lessons during vacations: show homework as unassigned instead
    if vacation:
        lessons = []

    hw_by_lesson: dict[int, list[Homework]] = {lesson.id: [] for lesson in lessons}
    unassigned: list[Homework] = []
    for hw in homeworks:
        if hw.lesson_id in hw_by_lesson:
            hw_by_lesson[hw.lesson_id].append(hw)
            continue
        candidates = [
            lesson
            for lesson in lessons
            if lesson.subject_id == hw.subject_id
            and (hw.subgroup is None or lesson.subgroup in (None, hw.subgroup))
        ]
        candidates.sort(key=lambda lesson: 0 if lesson.subgroup == hw.subgroup else 1)
        if candidates:
            hw_by_lesson[candidates[0].id].append(hw)
        else:
            unassigned.append(hw)

    return DaySummary(
        date=target,
        day_of_week=day_of_week,
        day_name=DAY_NAMES[day_of_week],
        vacation=vacation,
        lessons=[
            SummaryLesson(
                lesson_number=lesson.lesson_number,
                start_time=lesson.start_time,
                end_time=lesson.end_time,
                room=lesson.effective_room,
                teacher_name=lesson.effective_teacher_name,
                subgroup=lesson.subgroup,
                subject=lesson.subject,
                homework=hw_by_lesson[lesson.id],
            )
            for lesson in lessons
        ],
        unassigned_homework=unassigned,
    )
