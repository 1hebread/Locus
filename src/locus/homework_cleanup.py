import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from locus.constants import get_current_date
from locus.database import async_session_maker
from locus.models.homework import Homework
from locus.models.homework_event import HomeworkEvent

logger = logging.getLogger(__name__)

CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60


async def purge_old_homework(session: AsyncSession, retention_days: int) -> int:
    """Delete homework whose due date is older than the retention window."""
    cutoff = get_current_date() - timedelta(days=retention_days)
    result = await session.execute(delete(Homework).where(Homework.due_date < cutoff))
    await session.commit()
    return result.rowcount or 0


async def purge_old_homework_events(session: AsyncSession, retention_days: int) -> int:
    """Delete audit log entries older than the retention window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = await session.execute(
        delete(HomeworkEvent).where(HomeworkEvent.created_at < cutoff)
    )
    await session.commit()
    return result.rowcount or 0


async def run_homework_cleanup(retention_days: int) -> None:
    """Purge old homework and its audit log once a day for the app lifetime.

    shortcut: every worker runs its own loop, fine for the current single-node
    deployment; move to a shared scheduler if multiple app instances are added.
    """
    while True:
        try:
            async with async_session_maker() as session:
                removed = await purge_old_homework(session, retention_days)
                removed_events = await purge_old_homework_events(session, retention_days)
            if removed or removed_events:
                logger.info(
                    "Purged %d homework rows and %d audit events older than %d days",
                    removed,
                    removed_events,
                    retention_days,
                )
        except Exception:
            logger.exception("Homework cleanup failed")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
