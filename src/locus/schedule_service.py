from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from locus.models.homework import Homework
from locus.models.homework_completion import HomeworkCompletion
from locus.models.lesson import Lesson
from locus.schedule_validation import LessonConflictError, validate_lesson_conflict


class LessonNotFoundError(Exception):
    """Raised when the lesson to clone does not exist."""


async def clone_lesson_record(db: AsyncSession, lesson_id: int) -> Lesson:
    """Clone a lesson with the counterpart subgroup.

    - If subgroup is 1 -> clone for subgroup 2.
    - If subgroup is 2 -> clone for subgroup 1.
    - If whole-class (subgroup is None) -> convert source to subgroup 1,
      duplicate any attached homework with its completions, and clone for subgroup 2.
    - Room is taken from subject settings (subject.room / subject.room2).
      If the target subgroup has no room configured in subject settings, room is None
      (room is not copied from the counterpart subgroup).
    """
    stmt = (
        select(Lesson)
        .options(selectinload(Lesson.subject))
        .where(Lesson.id == lesson_id)
    )
    res = await db.execute(stmt)
    lesson = res.scalar_one_or_none()
    if not lesson:
        raise LessonNotFoundError("Урок не найден")

    is_whole_class = lesson.subgroup is None
    if lesson.subgroup == 1:
        target_subgroup = 2
    elif lesson.subgroup == 2:
        target_subgroup = 1
    else:
        target_subgroup = 2

    # Validate conflicts before making any modifications
    if is_whole_class:
        # Validate original lesson converting to subgroup 1
        await validate_lesson_conflict(
            db=db,
            day_of_week=lesson.day_of_week,
            lesson_number=lesson.lesson_number,
            start_time=lesson.start_time,
            end_time=lesson.end_time,
            week_type=lesson.week_type,
            subgroup=1,
            exclude_lesson_id=lesson.id,
        )
        # Validate clone as subgroup 2 (excluding the source lesson which becomes subgroup 1)
        await validate_lesson_conflict(
            db=db,
            day_of_week=lesson.day_of_week,
            lesson_number=lesson.lesson_number,
            start_time=lesson.start_time,
            end_time=lesson.end_time,
            week_type=lesson.week_type,
            subgroup=2,
            exclude_lesson_id=lesson.id,
        )
    else:
        await validate_lesson_conflict(
            db=db,
            day_of_week=lesson.day_of_week,
            lesson_number=lesson.lesson_number,
            start_time=lesson.start_time,
            end_time=lesson.end_time,
            week_type=lesson.week_type,
            subgroup=target_subgroup,
        )

    # Room is taken from subject settings:
    # If target is subgroup 2: subject.room2 (None if not set)
    # If target is subgroup 1: subject.room (None if not set)
    target_room = lesson.subject.get_room(target_subgroup) if lesson.subject else None

    cloned_lesson = Lesson(
        subject_id=lesson.subject_id,
        day_of_week=lesson.day_of_week,
        lesson_number=lesson.lesson_number,
        start_time=lesson.start_time,
        end_time=lesson.end_time,
        week_type=lesson.week_type,
        subgroup=target_subgroup,
        room=target_room,
        note=lesson.note,
    )
    db.add(cloned_lesson)
    await db.flush()

    if is_whole_class:
        lesson.subgroup = 1
        # Duplicate homeworks and their personal completions
        hw_stmt = (
            select(Homework)
            .options(selectinload(Homework.completions))
            .where(Homework.lesson_id == lesson.id)
        )
        hw_res = await db.execute(hw_stmt)
        for hw in hw_res.scalars().all():
            hw.subgroup = 1
            cloned_hw = Homework(
                subject_id=hw.subject_id,
                lesson_id=cloned_lesson.id,
                title=hw.title,
                due_date=hw.due_date,
                subgroup=2,
            )
            db.add(cloned_hw)
            await db.flush()
            for comp in hw.completions:
                cloned_comp = HomeworkCompletion(
                    homework_id=cloned_hw.id,
                    user_id=comp.user_id,
                    status=comp.status,
                )
                db.add(cloned_comp)

    await db.commit()

    # Re-fetch cloned lesson with loaded subject
    reload_stmt = (
        select(Lesson)
        .options(selectinload(Lesson.subject))
        .where(Lesson.id == cloned_lesson.id)
    )
    reload_res = await db.execute(reload_stmt)
    return reload_res.scalar_one()
