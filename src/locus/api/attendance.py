from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.attendance import apply_marks, build_day, mark_date_error
from locus.api.deps import get_current_headman, get_current_user
from locus.constants import get_current_date
from locus.database import get_db
from locus.models.student import Student
from locus.models.user import User
from locus.schemas.attendance import AttendanceDayOut, AttendanceMarksUpdate

router = APIRouter(prefix="/attendance", tags=["Attendance"])


@router.get("", response_model=AttendanceDayOut)
async def get_attendance(
    target_date: Optional[date] = Query(default=None, alias="date"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Class roster and attendance marks for one school day (today by default)."""
    target = target_date or get_current_date()
    can_edit = current_user.is_headman or current_user.is_admin
    return await build_day(db, target, can_edit=can_edit)


@router.put("/{target_date}", response_model=AttendanceDayOut)
async def update_attendance(
    payload: AttendanceMarksUpdate,
    target_date: date,
    current_user: User = Depends(get_current_headman),
    db: AsyncSession = Depends(get_db),
):
    """Apply marks for one date; a null status clears the mark (headman only)."""
    today = get_current_date()
    date_error = await mark_date_error(db, target_date, today)
    if date_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=date_error,
        )

    if payload.marks:
        student_ids = [mark.student_id for mark in payload.marks]
        found = set(
            (
                await db.execute(
                    select(Student.id).where(
                        Student.id.in_(student_ids),
                        Student.is_active == True,
                    )
                )
            ).scalars().all()
        )
        if any(student_id not in found for student_id in student_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ученик не найден",
            )

        await apply_marks(db, target_date, payload.marks, current_user.id)
        await db.commit()

    return await build_day(db, target_date, can_edit=True, today=today)
