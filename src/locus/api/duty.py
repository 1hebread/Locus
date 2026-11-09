from typing import List

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from locus.api.deps import get_current_admin, get_current_user
from locus.database import get_db
from locus.duty import load_duty_days, set_duty_text
from locus.models.user import User
from locus.schemas.duty import DutyDayOut, DutyDayUpdate

router = APIRouter(prefix="/duty", tags=["Duty"])


@router.get("", response_model=List[DutyDayOut])
async def list_duty_days(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Duty roster for all seven weekdays."""
    return await load_duty_days(db, current_user)


@router.put("/{day_of_week}", response_model=DutyDayOut)
async def update_duty_day(
    data: DutyDayUpdate,
    day_of_week: int = Path(ge=1, le=7),
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Replace one weekday's roster text (admin only)."""
    await set_duty_text(db, day_of_week, data.text)
    await db.commit()
    days = await load_duty_days(db, current_user)
    return days[day_of_week - 1]
