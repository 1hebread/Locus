from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from locus.api.deps import get_current_admin, get_current_user
from locus.constants import WeekType
from locus.database import get_db
from locus.models.lesson import Lesson
from locus.models.subject import Subject
from locus.models.user import User
from locus.schemas.lesson import LessonCreate, LessonOut, LessonUpdate

router = APIRouter(prefix="/schedule", tags=["Schedule"])


@router.get("", response_model=List[LessonOut])
async def list_schedule(
    day_of_week: Optional[int] = Query(default=None, ge=1, le=7),
    week_type: Optional[WeekType] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List shared schedule lessons with optional filtering by day and week cycle."""
    stmt = select(Lesson).options(selectinload(Lesson.subject))

    if day_of_week is not None:
        stmt = stmt.where(Lesson.day_of_week == day_of_week)

    if week_type is not None and week_type != WeekType.ALL:
        stmt = stmt.where(
            or_(
                Lesson.week_type == week_type.value,
                Lesson.week_type == WeekType.ALL.value,
            )
        )

    stmt = stmt.order_by(Lesson.day_of_week, Lesson.lesson_number)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=LessonOut, status_code=status.HTTP_201_CREATED)
async def create_lesson(
    data: LessonCreate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new shared lesson (admin only)."""
    subject = await db.get(Subject, data.subject_id)
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Выбранный предмет не найден",
        )

    lesson = Lesson(
        subject_id=data.subject_id,
        day_of_week=data.day_of_week,
        lesson_number=data.lesson_number,
        start_time=data.start_time or "08:00",
        end_time=data.end_time or "08:45",
        week_type=data.week_type.value,
        room=data.room if data.room is not None else subject.room,
        note=data.note,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)

    stmt = (
        select(Lesson)
        .options(selectinload(Lesson.subject))
        .where(Lesson.id == lesson.id)
    )
    res = await db.execute(stmt)
    return res.scalar_one()


@router.get("/{lesson_id}", response_model=LessonOut)
async def get_lesson(
    lesson_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get single lesson."""
    stmt = (
        select(Lesson)
        .options(selectinload(Lesson.subject))
        .where(Lesson.id == lesson_id)
    )
    res = await db.execute(stmt)
    lesson = res.scalar_one_or_none()
    if not lesson:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Урок не найден",
        )
    return lesson


@router.put("/{lesson_id}", response_model=LessonOut)
async def update_lesson(
    lesson_id: int,
    data: LessonUpdate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update lesson (admin only)."""
    stmt = (
        select(Lesson)
        .options(selectinload(Lesson.subject))
        .where(Lesson.id == lesson_id)
    )
    res = await db.execute(stmt)
    lesson = res.scalar_one_or_none()
    if not lesson:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Урок не найден",
        )

    if data.subject_id is not None and data.subject_id != lesson.subject_id:
        subject = await db.get(Subject, data.subject_id)
        if not subject:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Выбранный предмет не найден",
            )

    update_dict = data.model_dump(exclude_unset=True)
    if "week_type" in update_dict and update_dict["week_type"]:
        update_dict["week_type"] = update_dict["week_type"].value

    for key, val in update_dict.items():
        setattr(lesson, key, val)

    await db.commit()
    await db.refresh(lesson)

    res = await db.execute(stmt)
    return res.scalar_one()


@router.delete("/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson(
    lesson_id: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete lesson (admin only)."""
    lesson = await db.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Урок не найден",
        )

    await db.delete(lesson)
    await db.commit()
    return None
