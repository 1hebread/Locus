from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo

from locus.config import get_settings


class WeekType(str, Enum):
    ALL = "ALL"
    NUMERATOR = "NUMERATOR"
    DENOMINATOR = "DENOMINATOR"


class HomeworkStatus(str, Enum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


# Standard school bell schedule: 45 min lessons with breaks, starting at 08:00
DEFAULT_BELL_SCHEDULE: Dict[int, Tuple[str, str]] = {
    1: ("08:00", "08:45"),
    2: ("08:55", "09:40"),
    3: ("09:55", "10:40"),
    4: ("10:55", "11:40"),
    5: ("11:55", "12:40"),
    6: ("12:50", "13:35"),
    7: ("13:45", "14:30"),
    8: ("14:40", "15:25"),
}

DAY_NAMES: Dict[int, str] = {
    1: "Понедельник",
    2: "Вторник",
    3: "Среда",
    4: "Четверг",
    5: "Пятница",
    6: "Суббота",
    7: "Воскресенье",
}

DAY_SHORT_NAMES: Dict[int, str] = {
    1: "Пн",
    2: "Вт",
    3: "Ср",
    4: "Чт",
    5: "Пт",
    6: "Сб",
    7: "Вс",
}

MONTH_NAMES_GENITIVE: Dict[int, str] = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}

MONTH_NAMES_PREPOSITIONAL: Dict[int, str] = {
    1: "январь",
    2: "февраль",
    3: "март",
    4: "апрель",
    5: "май",
    6: "июнь",
    7: "июль",
    8: "август",
    9: "сентябрь",
    10: "октябрь",
    11: "ноябрь",
    12: "декабрь",
}


def get_current_datetime() -> datetime:
    """Get current datetime in configured timezone (default: Asia/Almaty)."""
    settings = get_settings()
    try:
        tz = ZoneInfo(settings.TIMEZONE)
    except Exception:
        tz = ZoneInfo("Asia/Almaty")
    return datetime.now(tz)


def get_current_date() -> date:
    """Get today's date in configured timezone (default: Asia/Almaty)."""
    return get_current_datetime().date()


def get_current_week_type(target_date: date | None = None) -> WeekType:
    """Return whether current week number is numerator (odd) or denominator (even)."""
    check_date = target_date or get_current_date()
    week_num = check_date.isocalendar()[1]
    return WeekType.NUMERATOR if week_num % 2 != 0 else WeekType.DENOMINATOR


def calculate_break_minutes(end_time_str: str, next_start_time_str: str) -> int:
    """Calculate break duration in minutes between lessons."""
    try:
        h1, m1 = map(int, end_time_str.split(":"))
        h2, m2 = map(int, next_start_time_str.split(":"))
        diff = (h2 * 60 + m2) - (h1 * 60 + m1)
        return diff if diff > 0 else 0
    except Exception:
        return 0


def format_russian_break(minutes: int) -> str:
    """Format minutes into Russian text: 'Перемена 10 минут'."""
    if minutes % 10 == 1 and minutes % 100 != 11:
        word = "минута"
    elif minutes % 10 in [2, 3, 4] and minutes % 100 not in [12, 13, 14]:
        word = "минуты"
    else:
        word = "минут"
    return f"Перемена {minutes} {word}"


def is_lesson_now(lesson_date: date, start_time: str, end_time: str) -> bool:
    """Check if lesson is currently in session (matches today's date and time window)."""
    settings = get_settings()
    try:
        tz = ZoneInfo(settings.TIMEZONE)
    except Exception:
        tz = ZoneInfo("Asia/Almaty")
    now_dt = datetime.now(tz)
    if lesson_date != now_dt.date():
        return False
    current_time_str = now_dt.strftime("%H:%M")
    return start_time <= current_time_str <= end_time


def get_week_days_data(selected_date: date) -> List[Dict[str, Any]]:
    """Return day list for the week containing selected_date."""
    today = get_current_date()
    # Monday of the current week (weekday() is 0 for Monday)
    start_monday = selected_date - timedelta(days=selected_date.weekday())
    result = []
    for i in range(7):
        day_date = start_monday + timedelta(days=i)
        day_num = i + 1  # 1..7
        result.append({
            "day_num": day_num,
            "name": DAY_NAMES[day_num],
            "name_upper": DAY_NAMES[day_num].upper(),
            "short_name": DAY_SHORT_NAMES[day_num],
            "day_number": day_date.day,
            "date": day_date,
            "date_iso": day_date.isoformat(),
            "is_today": (day_date == today),
            "is_selected": (day_date == selected_date),
        })
    return result
