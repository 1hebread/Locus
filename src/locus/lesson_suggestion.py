from datetime import date, datetime, timedelta
from typing import Any, List, Optional

from locus.constants import MONTH_NAMES_GENITIVE


def _format_next_date(next_date: date, start_time: str, today: date) -> str:
    """Human-friendly label for the next lesson date."""
    delta = (next_date - today).days
    if delta == 0:
        day_label = "сегодня"
    elif delta == 1:
        day_label = "завтра"
    elif delta == 2:
        day_label = "послезавтра"
    else:
        month = MONTH_NAMES_GENITIVE.get(next_date.month, "")
        day_label = f"{next_date.day} {month}".strip()
    return f"{day_label} в {start_time}"


def _find_next_subject_lesson(
    lessons: List[Any],
    source: Any,
    now: datetime,
    vacations: Optional[List[Any]] = None,
    subgroup: Optional[int] = None,
):
    """Find the next occurrence of the source lesson's subject after it, skipping vacations."""
    today = now.date()

    # Search forward up to 120 days so vacation periods (including summer breaks) are cleanly skipped
    for offset in range(0, 120):
        candidate_date = today + timedelta(days=offset)
        # Skip Sundays because homework cannot be assigned on Sundays
        if candidate_date.isoweekday() == 7:
            continue

        if vacations and any(v.start_date <= candidate_date <= v.end_date for v in vacations):
            continue

        weekday = candidate_date.isoweekday()
        target_subgroup = subgroup if subgroup is not None else getattr(source, "subgroup", None)
        same_day = sorted(
            (
                lesson
                for lesson in lessons
                if lesson.subject_id == source.subject_id
                and lesson.day_of_week == weekday
                and (
                    target_subgroup is None
                    or getattr(lesson, "subgroup", None) is None
                    or getattr(lesson, "subgroup", None) == target_subgroup
                )
            ),
            key=lambda lesson: lesson.start_time,
        )

        for lesson in same_day:
            # Skip the source itself and any earlier lesson of the same subject
            if offset == 0 and lesson.start_time <= source.end_time:
                continue
            return candidate_date, lesson

    return None


find_next_subject_lesson = _find_next_subject_lesson


def get_next_lesson_suggestion(
    lessons: List[Any],
    now: datetime,
    vacations: Optional[List[Any]] = None,
    subgroup: Optional[int] = None,
) -> Optional[dict]:
    """Build a quick-add suggestion for the next lesson of the current subject.

    During a lesson, the current lesson is the source. During a break after a
    lesson, the lesson that just ended is the source. The suggested due date is
    the next date that same subject appears in the schedule (skipping vacation periods).
    """
    today = now.date()
    if vacations and any(v.start_date <= today <= v.end_date for v in vacations):
        return None

    now_time = now.strftime("%H:%M")

    today_lessons = sorted(
        (
            lesson
            for lesson in lessons
            if lesson.day_of_week == today.isoweekday()
            and (
                subgroup is None
                or getattr(lesson, "subgroup", None) is None
                or getattr(lesson, "subgroup", None) == subgroup
            )
        ),
        key=lambda lesson: lesson.start_time,
    )
    if not today_lessons:
        return None

    current = next(
        (
            lesson
            for lesson in today_lessons
            if lesson.start_time <= now_time <= lesson.end_time
        ),
        None,
    )

    auto_apply = False
    if current:
        source = current
        auto_apply = True
    else:
        previous = [lesson for lesson in today_lessons if lesson.end_time < now_time]
        upcoming = [lesson for lesson in today_lessons if lesson.start_time > now_time]

        if previous and upcoming:
            # Break after a lesson (before the next one starts)
            source = previous[-1]
            auto_apply = True
        elif previous:
            # After school: keep the quick action useful for the last lesson
            source = previous[-1]
        else:
            # Before the first lesson there is no lesson to take homework from
            return None

    next_occurrence = _find_next_subject_lesson(
        lessons,
        source,
        now,
        vacations=vacations,
        subgroup=subgroup,
    )
    if not next_occurrence:
        return None

    next_date, next_lesson = next_occurrence
    subject = getattr(source, "subject", None)
    resolved_subgroup = getattr(next_lesson, "subgroup", None)

    return {
        "source_lesson_id": source.id,
        "target_lesson_id": next_lesson.id,
        "subject_id": source.subject_id,
        "subject_name": subject.name if subject else "",
        "subgroup": resolved_subgroup,
        "next_date_iso": next_date.isoformat(),
        "next_date_label": _format_next_date(next_date, next_lesson.start_time, today),
        "auto_apply": auto_apply,
    }
