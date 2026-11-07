from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from locus.constants import HomeworkStatus
from locus.models.homework import Homework
from locus.models.homework_completion import HomeworkCompletion
from locus.models.user import User


def next_valid_due_date(days_ahead: int = 1) -> date:
    """A future date the API accepts (it rejects homework due on Sunday)."""
    d = date.today() + timedelta(days=days_ahead)
    if d.isoweekday() == 7:
        d += timedelta(days=1)
    return d


async def add_homework(
    db: AsyncSession,
    user: User,
    *,
    subject_id: int,
    title: str,
    due_date: date,
    status: str = HomeworkStatus.TODO.value,
    lesson_id: int | None = None,
) -> Homework:
    hw = Homework(
        subject_id=subject_id,
        lesson_id=lesson_id,
        title=title,
        due_date=due_date,
    )
    db.add(hw)
    await db.flush()
    db.add(
        HomeworkCompletion(
            homework_id=hw.id,
            user_id=user.id,
            status=status,
        )
    )
    await db.commit()
    await db.refresh(hw)
    hw.status = status
    return hw


async def set_completion(
    db: AsyncSession,
    user: User,
    homework_id: int,
    status: str,
) -> HomeworkCompletion:
    completion = HomeworkCompletion(
        homework_id=homework_id,
        user_id=user.id,
        status=status,
    )
    db.add(completion)
    await db.commit()
    return completion
