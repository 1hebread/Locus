from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.constants import HomeworkStatus, get_current_date
from locus.homework_cleanup import purge_old_homework
from locus.models.homework import Homework
from locus.models.homework_completion import HomeworkCompletion
from locus.models.subject import Subject
from locus.models.user import User


@pytest.mark.asyncio
async def test_old_homework_is_purged(
    db_session: AsyncSession,
    test_subject: Subject,
    test_user: User,
):
    today = get_current_date()
    old = Homework(
        subject_id=test_subject.id,
        title="old",
        due_date=today - timedelta(days=31),
    )
    edge = Homework(
        subject_id=test_subject.id,
        title="edge",
        due_date=today - timedelta(days=30),
    )
    fresh = Homework(
        subject_id=test_subject.id,
        title="fresh",
        due_date=today,
    )
    db_session.add_all([old, edge, fresh])
    await db_session.commit()
    await db_session.refresh(old)

    db_session.add(
        HomeworkCompletion(
            homework_id=old.id,
            user_id=test_user.id,
            status=HomeworkStatus.DONE.value,
        )
    )
    await db_session.commit()

    removed = await purge_old_homework(db_session, 30)

    assert removed == 1
    titles = (
        await db_session.execute(select(Homework.title).order_by(Homework.title))
    ).scalars().all()
    assert titles == ["edge", "fresh"]
    # Completions of deleted homework are removed by the FK cascade
    assert await db_session.scalar(select(func.count(HomeworkCompletion.id))) == 0
