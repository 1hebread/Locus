from datetime import date, datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.config import get_settings
from locus.models.homework import Homework
from locus.models.homework_event import HomeworkEvent
from locus.models.user import User

ACTION_CREATED = "created"
ACTION_UPDATED = "updated"
ACTION_DELETED = "deleted"

FIELDS = ("subject_id", "lesson_id", "title", "due_date", "subgroup")


def _value(hw: Homework, field: str) -> Any:
    value = getattr(hw, field)
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def snapshot(hw: Homework) -> dict[str, Any]:
    return {field: _value(hw, field) for field in FIELDS}


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list]:
    has_changes = any(before.get(field) != after.get(field) for field in FIELDS)
    if not has_changes:
        return {}
    res = {
        field: [before[field], after[field]]
        for field in FIELDS
        if before[field] != after[field]
    }
    # Always persist subject_id and due_date context so audit logs remain self-contained
    # and immutable even if the homework record is rescheduled or deleted later
    if "subject_id" in before and "subject_id" in after:
        res["subject_id"] = [before["subject_id"], after["subject_id"]]
    if "due_date" in before and "due_date" in after:
        res["due_date"] = [before["due_date"], after["due_date"]]
    return res


def snapshot_changes(hw: Homework, deleted: bool = False) -> dict[str, list]:
    """Log a creation ("" -> value) or a deletion (value -> "") as change pairs."""
    changes = {}
    for field, value in snapshot(hw).items():
        if value is None:
            continue
        changes[field] = [value, None] if deleted else [None, value]
    return changes


def log_homework_event(
    db: AsyncSession,
    actor: User,
    action: str,
    homework_id: Optional[int],
    changes: dict[str, list],
) -> None:
    db.add(
        HomeworkEvent(
            homework_id=homework_id,
            actor_id=actor.id,
            actor_username=actor.username,
            actor_key_name=getattr(actor, "api_key_name", None),
            action=action,
            changes=changes,
        )
    )


async def get_last_event(db: AsyncSession, homework_id: int) -> Optional[HomeworkEvent]:
    result = await db.execute(
        select(HomeworkEvent)
        .where(HomeworkEvent.homework_id == homework_id)
        .order_by(HomeworkEvent.created_at.desc(), HomeworkEvent.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def local_datetime(value: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC like Postgres does."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo(get_settings().TIMEZONE))
