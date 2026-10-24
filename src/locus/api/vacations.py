from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.api.deps import get_current_admin, get_current_user
from locus.database import get_db
from locus.models.user import User
from locus.models.vacation import Vacation
from locus.schemas.vacation import VacationCreate, VacationOut, VacationUpdate

router = APIRouter(prefix="/vacations", tags=["Vacations"])


@router.get("", response_model=List[VacationOut])
async def list_vacations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all school vacations."""
    stmt = select(Vacation).order_by(Vacation.start_date.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=VacationOut, status_code=status.HTTP_201_CREATED)
async def create_vacation(
    data: VacationCreate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new vacation period (admin only)."""
    # Check for overlapping vacation periods
    overlap_stmt = select(Vacation).where(
        Vacation.start_date <= data.end_date,
        Vacation.end_date >= data.start_date,
    )
    overlap_res = await db.execute(overlap_stmt)
    overlap = overlap_res.scalars().first()
    if overlap:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Даты пересекаются с каникулами «{overlap.name}» ({overlap.start_date.strftime('%d.%m.%Y')}–{overlap.end_date.strftime('%d.%m.%Y')})",
        )

    vacation = Vacation(
        name=data.name,
        start_date=data.start_date,
        end_date=data.end_date,
    )
    db.add(vacation)
    await db.commit()
    await db.refresh(vacation)
    return vacation


@router.get("/{vacation_id}", response_model=VacationOut)
async def get_vacation(
    vacation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get single vacation by ID."""
    vacation = await db.get(Vacation, vacation_id)
    if not vacation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Каникулы не найдены",
        )
    return vacation


@router.put("/{vacation_id}", response_model=VacationOut)
async def update_vacation(
    vacation_id: int,
    data: VacationUpdate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update vacation period (admin only)."""
    vacation = await db.get(Vacation, vacation_id)
    if not vacation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Каникулы не найдены",
        )

    update_data = data.model_dump(exclude_unset=True)
    new_start = update_data.get("start_date", vacation.start_date)
    new_end = update_data.get("end_date", vacation.end_date)

    if new_start > new_end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Дата окончания не может быть раньше даты начала",
        )

    # Check for overlapping vacation periods excluding this vacation
    overlap_stmt = select(Vacation).where(
        Vacation.id != vacation_id,
        Vacation.start_date <= new_end,
        Vacation.end_date >= new_start,
    )
    overlap_res = await db.execute(overlap_stmt)
    overlap = overlap_res.scalars().first()
    if overlap:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Даты пересекаются с каникулами «{overlap.name}» ({overlap.start_date.strftime('%d.%m.%Y')}–{overlap.end_date.strftime('%d.%m.%Y')})",
        )

    for key, value in update_data.items():
        setattr(vacation, key, value)

    await db.commit()
    await db.refresh(vacation)
    return vacation


@router.delete("/{vacation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vacation(
    vacation_id: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete vacation period (admin only)."""
    vacation = await db.get(Vacation, vacation_id)
    if not vacation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Каникулы не найдены",
        )

    await db.delete(vacation)
    await db.commit()
    return None
