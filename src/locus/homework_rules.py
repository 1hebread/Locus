from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.models.homework import Homework

LESSON_SLOT_TAKEN = "На этот урок уже записано домашнее задание на эту дату"


async def lesson_homework_exists(
    db: AsyncSession,
    lesson_id: int,
    due_date: date,
    exclude_id: int | None = None,
) -> bool:
    """A lesson holds at most one assignment per due date."""
    stmt = select(Homework.id).where(
        Homework.lesson_id == lesson_id,
        Homework.due_date == due_date,
    )
    if exclude_id is not None:
        stmt = stmt.where(Homework.id != exclude_id)
    return (await db.execute(stmt.limit(1))).scalar_one_or_none() is not None
