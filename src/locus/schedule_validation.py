import re
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from locus.constants import WeekType
from locus.models.lesson import Lesson

TIME_REGEX = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class LessonConflictError(Exception):
    """Raised when a lesson has conflicting lesson number or overlapping time."""


def check_week_overlap(week1: str, week2: str) -> bool:
    """Check if two week types can co-occur."""
    return (
        week1 == WeekType.ALL.value
        or week2 == WeekType.ALL.value
        or week1 == week2
    )


def check_subgroup_overlap(subgroup1: Optional[int], subgroup2: Optional[int]) -> bool:
    """Check if two lessons affect the same student audience.

    If either lesson is for the whole class (None or 0), they overlap.
    If both belong to explicit subgroups, they overlap only if the subgroups are equal.
    """
    if not subgroup1 or not subgroup2:
        return True
    return subgroup1 == subgroup2


def check_time_overlap(start1: str, end1: str, start2: str, end2: str) -> bool:
    """Return True if time intervals [start1, end1) and [start2, end2) overlap."""
    return start1 < end2 and end1 > start2


def validate_lesson_times(start_time: str, end_time: str) -> None:
    """Validate format and logical order of lesson times."""
    if not TIME_REGEX.match(start_time) or not TIME_REGEX.match(end_time):
        raise LessonConflictError("Неверный формат времени (ожидается ЧЧ:ММ)")
    if start_time >= end_time:
        raise LessonConflictError("Время окончания урока должно быть позже времени начала")


async def validate_lesson_conflict(
    db: AsyncSession,
    day_of_week: int,
    lesson_number: int,
    start_time: str,
    end_time: str,
    week_type: str = WeekType.ALL.value,
    subgroup: Optional[int] = None,
    exclude_lesson_id: Optional[int] = None,
) -> None:
    """Validate that lesson number and times do not conflict with existing lessons on the same day."""
    validate_lesson_times(start_time, end_time)

    stmt = (
        select(Lesson)
        .options(selectinload(Lesson.subject))
        .where(Lesson.day_of_week == day_of_week)
    )
    if exclude_lesson_id is not None:
        stmt = stmt.where(Lesson.id != exclude_lesson_id)

    res = await db.execute(stmt)
    existing_lessons = res.scalars().all()

    for other in existing_lessons:
        if not check_week_overlap(week_type, other.week_type):
            continue

        if not check_subgroup_overlap(subgroup, other.subgroup):
            continue

        if other.lesson_number == lesson_number:
            if other.subgroup:
                group_info = f" для подгруппы {other.subgroup}"
            elif subgroup:
                group_info = " (для всего класса)"
            else:
                group_info = ""
            raise LessonConflictError(
                f"Урок №{lesson_number}{group_info} в этот день уже существует"
            )

        if check_time_overlap(start_time, end_time, other.start_time, other.end_time):
            subj_name = other.subject.name if other.subject else "Урок"
            raise LessonConflictError(
                f"Время урока ({start_time}–{end_time}) пересекается с уроком №{other.lesson_number} «{subj_name}» ({other.start_time}–{other.end_time})"
            )
