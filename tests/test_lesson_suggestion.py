from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from locus.lesson_suggestion import get_next_lesson_suggestion

TZ = ZoneInfo("Asia/Almaty")


def make_lesson(
    lesson_id: int,
    subject_id: int,
    subject_name: str,
    day_of_week: int,
    start_time: str,
    end_time: str,
):
    return SimpleNamespace(
        id=lesson_id,
        subject_id=subject_id,
        subject=SimpleNamespace(name=subject_name),
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time,
    )


def test_suggestion_during_lesson_uses_current_subject_and_next_date():
    """During a lesson the current subject is used, with its next occurrence."""
    lessons = [
        make_lesson(1, 1, "Алгебра", 4, "08:30", "09:15"),
        make_lesson(2, 1, "Алгебра", 1, "08:30", "09:15"),
        make_lesson(3, 2, "Физика", 4, "10:00", "10:45"),
    ]
    now = datetime(2026, 10, 22, 9, 0, tzinfo=TZ)  # Thursday, during Algebra

    suggestion = get_next_lesson_suggestion(lessons, now)

    assert suggestion is not None
    assert suggestion["source_lesson_id"] == 1
    assert suggestion["target_lesson_id"] == 2
    assert suggestion["subject_id"] == 1
    assert suggestion["subject_name"] == "Алгебра"
    assert suggestion["next_date_iso"] == "2026-10-26"
    assert suggestion["next_date_label"] == "26 октября в 08:30"
    assert suggestion["auto_apply"] is True


def test_suggestion_during_break_uses_previous_lesson():
    """A break after a lesson keeps that just-finished lesson as the source."""
    lessons = [
        make_lesson(1, 1, "Алгебра", 4, "08:30", "09:15"),
        make_lesson(2, 2, "Физика", 4, "10:00", "10:45"),
        make_lesson(3, 1, "Алгебра", 5, "08:30", "09:15"),
    ]
    now = datetime(2026, 10, 22, 9, 20, tzinfo=TZ)  # Thursday break

    suggestion = get_next_lesson_suggestion(lessons, now)

    assert suggestion is not None
    assert suggestion["source_lesson_id"] == 1
    assert suggestion["target_lesson_id"] == 3
    assert suggestion["subject_name"] == "Алгебра"
    assert suggestion["next_date_iso"] == "2026-10-23"
    assert suggestion["next_date_label"] == "завтра в 08:30"
    assert suggestion["auto_apply"] is True


def test_suggestion_finds_later_lesson_of_same_subject_today():
    """If the subject repeats later today, that is the next occurrence."""
    lessons = [
        make_lesson(1, 1, "Алгебра", 4, "08:30", "09:15"),
        make_lesson(2, 1, "Алгебра", 4, "11:00", "11:45"),
    ]
    now = datetime(2026, 10, 22, 9, 0, tzinfo=TZ)

    suggestion = get_next_lesson_suggestion(lessons, now)

    assert suggestion is not None
    assert suggestion["target_lesson_id"] == 2
    assert suggestion["next_date_iso"] == "2026-10-22"
    assert suggestion["next_date_label"] == "сегодня в 11:00"


def test_suggestion_after_school_is_not_auto_applied():
    """After the last lesson the quick action still works, but does not auto-fill."""
    lessons = [
        make_lesson(1, 1, "Алгебра", 4, "08:30", "09:15"),
        make_lesson(2, 2, "Физика", 4, "10:00", "10:45"),
    ]
    now = datetime(2026, 10, 22, 16, 0, tzinfo=TZ)

    suggestion = get_next_lesson_suggestion(lessons, now)

    assert suggestion is not None
    assert suggestion["source_lesson_id"] == 2
    assert suggestion["target_lesson_id"] == 2
    assert suggestion["subject_name"] == "Физика"
    assert suggestion["next_date_iso"] == "2026-10-29"
    assert suggestion["auto_apply"] is False


def test_suggestion_is_none_before_first_lesson():
    """There is no current or previous lesson before the school day starts."""
    lessons = [
        make_lesson(1, 1, "Алгебра", 4, "08:30", "09:15"),
    ]
    now = datetime(2026, 10, 22, 7, 30, tzinfo=TZ)

    assert get_next_lesson_suggestion(lessons, now) is None


def test_suggestion_is_none_without_lessons_today():
    """No source lesson means no quick action."""
    lessons = [
        make_lesson(1, 1, "Алгебра", 5, "08:30", "09:15"),
    ]
    now = datetime(2026, 10, 22, 9, 0, tzinfo=TZ)  # Thursday, lesson only on Friday

    assert get_next_lesson_suggestion(lessons, now) is None


def test_suggestion_skips_vacation_period_to_next_school_day():
    """If next occurrence falls in a vacation, suggestion skips forward to next school day."""
    from datetime import date
    lessons = [
        make_lesson(1, 1, "Алгебра", 5, "08:30", "09:15"),  # Friday
        make_lesson(2, 1, "Алгебра", 1, "08:30", "09:15"),  # Monday
    ]
    # Friday 2026-10-23
    now = datetime(2026, 10, 23, 9, 0, tzinfo=TZ)
    # Vacation 2026-10-26 through 2026-11-01 (skips Monday 2026-10-26)
    vacations = [
        SimpleNamespace(
            start_date=date(2026, 10, 26),
            end_date=date(2026, 11, 1),
        )
    ]

    suggestion = get_next_lesson_suggestion(lessons, now, vacations=vacations)
    assert suggestion is not None
    # Next Monday after vacation is 2026-11-02
    assert suggestion["next_date_iso"] == "2026-11-02"
    assert "2 ноября" in suggestion["next_date_label"]


def test_suggestion_is_none_during_vacation():
    """During active vacation, no next lesson is suggested."""
    from datetime import date
    lessons = [
        make_lesson(1, 1, "Алгебра", 1, "08:30", "09:15"),
    ]
    now = datetime(2026, 10, 26, 9, 0, tzinfo=TZ)
    vacations = [
        SimpleNamespace(
            start_date=date(2026, 10, 26),
            end_date=date(2026, 11, 1),
        )
    ]
    assert get_next_lesson_suggestion(lessons, now, vacations=vacations) is None


def test_suggestion_skips_sunday_to_next_weekday():
    """If the next occurrence by schedule is on Sunday (day 7), it must be skipped because homework is not allowed on Sundays."""
    lessons = [
        make_lesson(1, 1, "Алгебра", 5, "08:30", "09:15"),  # Friday
        make_lesson(2, 1, "Алгебра", 7, "10:00", "10:45"),  # Sunday elective
        make_lesson(3, 1, "Алгебра", 1, "08:30", "09:15"),  # Next Monday
    ]
    # Friday 2026-10-23
    now = datetime(2026, 10, 23, 9, 0, tzinfo=TZ)

    suggestion = get_next_lesson_suggestion(lessons, now)
    assert suggestion is not None
    # Must skip Sunday 2026-10-25 and choose Monday 2026-10-26
    assert suggestion["target_lesson_id"] == 3
    assert suggestion["next_date_iso"] == "2026-10-26"
    assert "26 октября" in suggestion["next_date_label"]
