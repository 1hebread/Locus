import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.constants import get_current_date
from locus.database import async_session_maker
from locus.models.attendance import AttendanceRecord
from locus.models.student import Student

logger = logging.getLogger(__name__)

CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60


async def purge_old_attendance(session: AsyncSession, retention_days: int) -> int:
    """Delete attendance marks older than the retention window."""
    cutoff = get_current_date() - timedelta(days=retention_days)
    result = await session.execute(
        delete(AttendanceRecord).where(AttendanceRecord.attendance_date < cutoff)
    )
    await session.commit()
    return result.rowcount or 0


async def purge_archived_students(session: AsyncSession) -> int:
    """Delete archived students that have no attendance marks left."""
    remaining_student_ids = select(AttendanceRecord.student_id)
    result = await session.execute(
        delete(Student).where(
            Student.is_active == False,
            Student.id.not_in(remaining_student_ids),
        )
    )
    await session.commit()
    return result.rowcount or 0


async def run_attendance_cleanup(retention_days: int) -> None:
    """Purge old attendance and empty archived students once a day."""
    while True:
        try:
            async with async_session_maker() as session:
                removed_marks = await purge_old_attendance(session, retention_days)
                removed_students = await purge_archived_students(session)
            if removed_marks or removed_students:
                logger.info(
                    "Purged %d attendance rows older than %d days and %d archived "
                    "students without marks",
                    removed_marks,
                    retention_days,
                    removed_students,
                )
        except Exception:
            logger.exception("Attendance cleanup failed")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
