from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from locus.constants import HomeworkStatus
from locus.models.homework import Homework
from locus.models.homework_completion import HomeworkCompletion


def apply_status(hw: Homework, status: str | None) -> Homework:
    """Attach the current user's per-homework status for templates/API output."""
    hw.status = status or HomeworkStatus.TODO.value
    return hw


async def load_statuses(
    db: AsyncSession,
    homework_ids: Iterable[int],
    user_id: int,
) -> dict[int, str]:
    ids = list(homework_ids)
    if not ids:
        return {}
    result = await db.execute(
        select(HomeworkCompletion.homework_id, HomeworkCompletion.status).where(
            HomeworkCompletion.user_id == user_id,
            HomeworkCompletion.homework_id.in_(ids),
        )
    )
    return dict(result.all())


async def attach_statuses(
    db: AsyncSession,
    homeworks: Sequence[Homework],
    user_id: int,
) -> list[Homework]:
    statuses = await load_statuses(db, [hw.id for hw in homeworks], user_id)
    for hw in homeworks:
        apply_status(hw, statuses.get(hw.id))
    return list(homeworks)


async def attach_status(db: AsyncSession, hw: Homework, user_id: int) -> Homework:
    status = await db.scalar(
        select(HomeworkCompletion.status).where(
            HomeworkCompletion.homework_id == hw.id,
            HomeworkCompletion.user_id == user_id,
        )
    )
    return apply_status(hw, status)


async def get_completion(
    db: AsyncSession,
    homework_id: int,
    user_id: int,
) -> HomeworkCompletion | None:
    return await db.scalar(
        select(HomeworkCompletion).where(
            HomeworkCompletion.homework_id == homework_id,
            HomeworkCompletion.user_id == user_id,
        )
    )


async def set_status(
    db: AsyncSession,
    homework_id: int,
    user_id: int,
    status: str,
) -> HomeworkCompletion:
    completion = await get_completion(db, homework_id, user_id)
    if completion:
        completion.status = status
        return completion

    try:
        async with db.begin_nested():
            completion = HomeworkCompletion(
                homework_id=homework_id,
                user_id=user_id,
                status=status,
            )
            db.add(completion)
            await db.flush()
            return completion
    except IntegrityError:
        completion = await get_completion(db, homework_id, user_id)
        if completion:
            completion.status = status
            return completion
        raise
