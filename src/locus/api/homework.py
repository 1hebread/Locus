from datetime import date
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from locus.api.deps import get_current_user
from locus.constants import HomeworkStatus
from locus.database import get_db
from locus.homework_audit import (
    ACTION_CREATED,
    ACTION_DELETED,
    ACTION_UPDATED,
    diff,
    log_homework_event,
    snapshot,
    snapshot_changes,
)
from locus.homework_rules import LESSON_SLOT_TAKEN, lesson_homework_exists
from locus.homework_status import attach_status, attach_statuses, set_status
from locus.models.homework import Homework
from locus.models.homework_completion import HomeworkCompletion
from locus.models.lesson import Lesson
from locus.models.subject import Subject
from locus.models.user import User
from locus.push import notify_homework_change
from locus.schemas.homework import (
    HomeworkCreate,
    HomeworkOut,
    HomeworkStatusUpdate,
    HomeworkUpdate,
)
from locus.subgroup_helpers import build_user_subgroup_filter, user_matches_subgroup

router = APIRouter(prefix="/homework", tags=["Homework"])


@router.get("", response_model=List[HomeworkOut])
async def list_homework(
    status_filter: Optional[HomeworkStatus] = Query(default=None, alias="status"),
    subject_id: Optional[int] = Query(default=None),
    due_date: Optional[date] = Query(default=None),
    due_from: Optional[date] = Query(default=None),
    due_to: Optional[date] = Query(default=None),
    subgroup: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List shared homework with per-user status and flexible filters."""
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
    )

    # Subgroup isolation
    user_filter = build_user_subgroup_filter(current_user, Homework.subgroup)
    if user_filter is not None:
        stmt = stmt.where(user_filter)
    elif subgroup is not None and str(subgroup).strip() and str(subgroup).strip() != "all":
        stmt = stmt.where(
            or_(
                Homework.subgroup.is_(None),
                Homework.subgroup == str(subgroup).strip(),
            )
        )

    if status_filter == HomeworkStatus.DONE:
        stmt = stmt.where(HomeworkCompletion.status == HomeworkStatus.DONE.value)
    elif status_filter == HomeworkStatus.TODO:
        stmt = stmt.where(
            or_(
                HomeworkCompletion.id.is_(None),
                HomeworkCompletion.status != HomeworkStatus.DONE.value,
            )
        )
    elif status_filter == HomeworkStatus.IN_PROGRESS:
        stmt = stmt.where(HomeworkCompletion.status == HomeworkStatus.IN_PROGRESS.value)

    if subject_id is not None:
        stmt = stmt.where(Homework.subject_id == subject_id)
    if due_date is not None:
        stmt = stmt.where(Homework.due_date == due_date)
    if due_from is not None:
        stmt = stmt.where(Homework.due_date >= due_from)
    if due_to is not None:
        stmt = stmt.where(Homework.due_date <= due_to)

    stmt = stmt.order_by(Homework.due_date.asc(), Homework.id.desc())
    result = await db.execute(stmt)
    homeworks = list(result.scalars().all())
    return await attach_statuses(db, homeworks, current_user.id)


@router.post("", response_model=HomeworkOut, status_code=status.HTTP_201_CREATED)
async def create_homework(
    data: HomeworkCreate,
    background: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create shared homework assignment."""
    subject = await db.get(Subject, data.subject_id)
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Выбранный предмет не найден",
        )

    resolved_subgroup = data.subgroup
    lesson = None
    if data.lesson_id is not None:
        lesson = await db.get(Lesson, data.lesson_id)
        if not lesson:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Выбранный урок не найден",
            )
        if data.subgroup is not None and lesson.subgroup is not None and str(data.subgroup) != str(lesson.subgroup):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Подгруппа задания не совпадает с подгруппой урока",
            )
        if resolved_subgroup is None:
            resolved_subgroup = lesson.subgroup

    if not user_matches_subgroup(current_user, resolved_subgroup):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нельзя создать задание для чужой подгруппы",
        )
    if lesson and not user_matches_subgroup(current_user, lesson.subgroup):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нельзя привязать задание к уроку чужой подгруппы",
        )
    if lesson is not None and await lesson_homework_exists(db, lesson.id, data.due_date):
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
        subject_id=data.subject_id,
        lesson_id=data.lesson_id,
        title=data.title,
        due_date=data.due_date,
        subgroup=resolved_subgroup,
    )
    db.add(hw)
    try:
        await db.flush()
    except IntegrityError:
        # Unique index (lesson_id, due_date) caught a concurrent duplicate.
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=LESSON_SLOT_TAKEN)
    await set_status(db, hw.id, current_user.id, data.status.value)
    log_homework_event(db, current_user, ACTION_CREATED, hw.id, snapshot_changes(hw))
    await db.commit()
    notify_homework_change(
        background, current_user, ACTION_CREATED, hw.id, hw.title, subject.name, hw.subgroup, hw.due_date
    )

    stmt = (
        select(Homework)
        .options(selectinload(Homework.subject))
        .where(Homework.id == hw.id)
    )
    res = await db.execute(stmt)
    return await attach_status(db, res.scalar_one(), current_user.id)


@router.get("/{hw_id}", response_model=HomeworkOut)
async def get_homework(
    hw_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get single homework assignment."""
    stmt = (
        select(Homework)
        .options(selectinload(Homework.subject))
        .where(Homework.id == hw_id)
    )
    res = await db.execute(stmt)
    hw = res.scalar_one_or_none()
    if not hw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Домашнее задание не найдено",
        )
    if not user_matches_subgroup(current_user, hw.subgroup):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Домашнее задание не найдено",
        )
    return await attach_status(db, hw, current_user.id)


@router.put("/{hw_id}", response_model=HomeworkOut)
async def update_homework(
    hw_id: int,
    data: HomeworkUpdate,
    background: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update shared homework content and current user's status."""
    stmt = (
        select(Homework)
        .options(selectinload(Homework.subject))
        .where(Homework.id == hw_id)
    )
    res = await db.execute(stmt)
    hw = res.scalar_one_or_none()
    if not hw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Домашнее задание не найдено",
        )

    if not user_matches_subgroup(current_user, hw.subgroup):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нельзя изменять задание чужой подгруппы",
        )
    if not user_matches_subgroup(current_user, data.subgroup):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нельзя назначить задание чужой подгруппе",
        )

    if data.subject_id is not None and data.subject_id != hw.subject_id:
        subject = await db.get(Subject, data.subject_id)
        if not subject:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Выбранный предмет не найден",
            )

    if data.lesson_id is not None:
        lesson = await db.get(Lesson, data.lesson_id)
        if not lesson:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Выбранный урок не найден",
            )

    update_dict = data.model_dump(exclude_unset=True)

    target_lesson_id = update_dict.get("lesson_id", hw.lesson_id)
    target_lesson = None
    if target_lesson_id is not None:
        target_lesson = await db.get(Lesson, target_lesson_id)
        if target_lesson and target_lesson.subgroup is not None:
            if "subgroup" not in update_dict:
                update_dict["subgroup"] = target_lesson.subgroup
            elif update_dict["subgroup"] is not None and str(update_dict["subgroup"]) != str(target_lesson.subgroup):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Подгруппа задания не совпадает с подгруппой урока",
                )

    new_subgroup = update_dict.get("subgroup", hw.subgroup)
    if not user_matches_subgroup(current_user, new_subgroup):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нельзя назначить задание чужой подгруппе",
        )
    if target_lesson and not user_matches_subgroup(current_user, target_lesson.subgroup):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нельзя привязать задание к уроку чужой подгруппы",
        )
    # Only a move onto a new slot can create a duplicate; a plain edit of a
    # legacy duplicate must stay possible.
    if (
        target_lesson_id is not None
        and ("lesson_id" in update_dict or "due_date" in update_dict)
        and await lesson_homework_exists(
            db,
            target_lesson_id,
            update_dict.get("due_date") or hw.due_date,
            exclude_id=hw.id,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=LESSON_SLOT_TAKEN,
        )

    if "subgroup" in update_dict and update_dict["subgroup"] is not None:
        target_subject_id = update_dict.get("subject_id", hw.subject_id)
        target_subject = await db.get(Subject, target_subject_id)
        has_subgroups = bool(target_subject and target_subject.teacher2_name and target_subject.teacher2_name.strip())
        if not has_subgroups:
            sub_lesson = await db.execute(
                select(Lesson.id).where(Lesson.subject_id == target_subject_id, Lesson.subgroup.is_not(None)).limit(1)
            )
            has_subgroups = sub_lesson.scalar_one_or_none() is not None
        if not has_subgroups:
            update_dict["subgroup"] = None

    new_status = update_dict.pop("status", None)
    before = snapshot(hw)
    for key, val in update_dict.items():
        setattr(hw, key, val)

    changes = diff(before, snapshot(hw))
    if changes:
        log_homework_event(db, current_user, ACTION_UPDATED, hw.id, changes)

    if new_status is not None:
        await set_status(db, hw.id, current_user.id, new_status.value)

    try:
        await db.commit()
    except IntegrityError:
        # Unique index (lesson_id, due_date) caught a concurrent duplicate.
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=LESSON_SLOT_TAKEN)

    res = await db.execute(stmt)
    hw = res.scalar_one()
    if changes:
        notify_homework_change(
            background, current_user, ACTION_UPDATED, hw.id, hw.title, hw.subject.name, hw.subgroup, hw.due_date
        )
    return await attach_status(db, hw, current_user.id)


@router.patch("/{hw_id}/status", response_model=HomeworkOut)
async def update_homework_status(
    hw_id: int,
    data: HomeworkStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Quickly update the current user's homework status."""
    stmt = (
        select(Homework)
        .options(selectinload(Homework.subject))
        .where(Homework.id == hw_id)
    )
    res = await db.execute(stmt)
    hw = res.scalar_one_or_none()
    if not hw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Домашнее задание не найдено",
        )

    if not user_matches_subgroup(current_user, hw.subgroup):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Домашнее задание не найдено",
        )

    await set_status(db, hw.id, current_user.id, data.status.value)
    await db.commit()

    res = await db.execute(stmt)
    return await attach_status(db, res.scalar_one(), current_user.id)


@router.delete("/{hw_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_homework(
    hw_id: int,
    background: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete shared homework assignment."""
    hw = await db.get(Homework, hw_id)
    if not hw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Домашнее задание не найдено",
        )

    if not user_matches_subgroup(current_user, hw.subgroup):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нельзя удалить задание чужой подгруппы",
        )

    subject = await db.get(Subject, hw.subject_id)
    notify_homework_change(
        background, current_user, ACTION_DELETED, hw.id, hw.title, subject.name if subject else "", hw.subgroup, hw.due_date
    )
    log_homework_event(
        db, current_user, ACTION_DELETED, None, snapshot_changes(hw, deleted=True)
    )
    await db.delete(hw)
    await db.commit()
    return None
