from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.api.deps import get_current_admin, get_current_user
from locus.database import get_db
from locus.models.subject import Subject
from locus.models.user import User
from locus.schemas.subject import SubjectCreate, SubjectOut, SubjectUpdate

router = APIRouter(prefix="/subjects", tags=["Subjects"])


@router.get("", response_model=List[SubjectOut])
async def list_subjects(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all shared subjects."""
    stmt = select(Subject).order_by(Subject.name)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=SubjectOut, status_code=status.HTTP_201_CREATED)
async def create_subject(
    data: SubjectCreate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new shared subject (admin only)."""
    subject = Subject(
        name=data.name,
        teacher_name=data.teacher_name,
        teacher_phone=data.teacher_phone,
        room=data.room,
    )
    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    return subject


@router.get("/{subject_id}", response_model=SubjectOut)
async def get_subject(
    subject_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get single subject by ID."""
    subject = await db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Предмет не найден",
        )
    return subject


@router.put("/{subject_id}", response_model=SubjectOut)
async def update_subject(
    subject_id: int,
    data: SubjectUpdate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update subject (admin only)."""
    subject = await db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Предмет не найден",
        )

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(subject, key, value)

    await db.commit()
    await db.refresh(subject)
    return subject


@router.delete("/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subject(
    subject_id: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete subject (admin only)."""
    subject = await db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Предмет не найден",
        )

    await db.delete(subject)
    await db.commit()
    return None
