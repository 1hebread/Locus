import re
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.constants import DAY_NAMES, get_current_date
from locus.models.duty_day import DutyDay
from locus.models.user import User

# "Иван И. (ivan)" binds the entry to the user with that login
DUTY_LOGIN_PATTERN = re.compile(r"^(?P<name>.+?)\s*\((?P<login>[^()]*)\)\s*$")


def parse_duty_day(text: Optional[str]) -> List[Dict[str, Any]]:
    """Split a day's text into entries, one per non-empty line.

    Each entry has "name" and "login" (None when the line has no login);
    load_duty_days() adds "linked" once it knows which logins exist.
    """
    entries: List[Dict[str, Any]] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = DUTY_LOGIN_PATTERN.match(line)
        if match and match.group("name").strip() and match.group("login").strip():
            entries.append(
                {"name": match.group("name").strip(), "login": match.group("login").strip()}
            )
        else:
            entries.append({"name": line, "login": None})
    return entries


async def load_duty_days(db: AsyncSession, current_user: User) -> List[Dict[str, Any]]:
    """The six school weekdays (Monday to Saturday) with parsed entries.

    Each entry gets "linked" (its login belongs to a real user) and "is_me"
    (that user is the one viewing the roster).
    """
    rows = (await db.execute(select(DutyDay))).scalars().all()
    texts = {row.day_of_week: row.text for row in rows}
    today = get_current_date().isoweekday()

    days = [
        {
            "day_of_week": day_num,
            "name": DAY_NAMES[day_num],
            "text": texts.get(day_num, ""),
            "entries": parse_duty_day(texts.get(day_num, "")),
            "is_today": day_num == today,
        }
        for day_num in range(1, 7)
    ]

    logins = {
        entry["login"].lower() for day in days for entry in day["entries"] if entry["login"]
    }
    linked_logins = set()
    if logins:
        result = await db.execute(
            select(User.username).where(func.lower(User.username).in_(logins))
        )
        linked_logins = {username.lower() for username in result.scalars().all()}

    for day in days:
        for entry in day["entries"]:
            login = entry["login"].lower() if entry["login"] else None
            entry["linked"] = bool(login) and login in linked_logins
            entry["is_me"] = entry["linked"] and login == current_user.username.lower()
    return days


async def set_duty_text(db: AsyncSession, day_of_week: int, text: str) -> DutyDay:
    """Upsert one weekday's text; the caller commits."""
    row = await db.get(DutyDay, day_of_week)
    if row is None:
        row = DutyDay(day_of_week=day_of_week, text=text)
        db.add(row)
    else:
        row.text = text
    return row
