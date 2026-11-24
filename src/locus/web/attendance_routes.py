from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from locus.api.deps import get_current_headman_web, get_current_user_web
from locus.attendance import (
    RosterTextError,
    build_day,
    get_active_student,
    mark_date_error,
    mark_unmarked_present,
    sync_roster,
    toggle_mark,
)
from locus.constants import (
    ATTENDANCE_ABSENCE_STATUSES,
    ATTENDANCE_STATUS_LABELS,
    ATTENDANCE_STATUS_SHORT_LABELS,
    DAY_NAMES,
    MONTH_NAMES_GENITIVE,
    AttendanceStatus,
    get_current_date,
)
from locus.database import get_db
from locus.models.user import User
from locus.templates_config import templates

router = APIRouter(prefix="/attendance", tags=["Web Attendance"])

COUNT_ITEMS = [
    ("present", "Был", "text-accent-ink"),
    ("absent", "Нет", "text-danger-ink"),
    ("late", "Опоздал", "text-warning-ink"),
    ("excused", "Уваж.", "text-fg-muted"),
    ("sick", "Болезнь", "text-info-ink"),
    ("unmarked", "Не отмечено", "text-fg-subtle"),
]


def _status_option(item: AttendanceStatus) -> dict:
    return {
        "value": item.value,
        "label": ATTENDANCE_STATUS_LABELS[item.value],
        "short": ATTENDANCE_STATUS_SHORT_LABELS[item.value],
    }


ABSENCE_OPTIONS = [_status_option(item) for item in ATTENDANCE_ABSENCE_STATUSES]

STATUS_OPTIONS = [
    {
        **_status_option(item),
        **({"children": ABSENCE_OPTIONS} if item is AttendanceStatus.ABSENT else {}),
    }
    for item in (
        AttendanceStatus.PRESENT,
        AttendanceStatus.ABSENT,
        AttendanceStatus.LATE,
        AttendanceStatus.EXCUSED,
        AttendanceStatus.SICK,
    )
]

ERROR_MESSAGES = {
    "text_too_long": "Слишком длинный список класса",
    "name_too_long": "Слишком длинное имя ученика (максимум 255 символов)",
}


def _parse_date(raw: str | None) -> date:
    if not raw:
        return get_current_date()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Некорректная дата",
        )


def _redirect_day(target: date, error: str | None = None) -> RedirectResponse:
    url = f"/attendance?date={target.isoformat()}"
    if error:
        url += f"&error={error}"
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


def _count_values(day) -> dict[str, int]:
    return {key: getattr(day.counts, key) for key, _, _ in COUNT_ITEMS}


ABSENT_REPORT_REASONS = {
    AttendanceStatus.ABSENT.value: "отсутствует",
    AttendanceStatus.ABSENT_UNKNOWN.value: "неизвестно",
    AttendanceStatus.LEFT.value: "ушёл",
    AttendanceStatus.EXCUSED.value: "уважительная причина",
    AttendanceStatus.SICK.value: "болеет",
}


def _absent_report(day) -> str:
    """Names of everyone missing today with a plain-language reason."""
    return "\n".join(
        f"{student.full_name} — {ABSENT_REPORT_REASONS[student.status]}"
        for student in day.students
        if student.status in ABSENT_REPORT_REASONS
    )


def _day_context(day) -> dict:
    return {
        "day": day,
        "selected_iso": day.date.isoformat(),
        "status_options": STATUS_OPTIONS,
        "status_labels": ATTENDANCE_STATUS_LABELS,
        "count_items": COUNT_ITEMS,
        "count_values": _count_values(day),
        "absence_values": [status.value for status in ATTENDANCE_ABSENCE_STATUSES],
        "absent_report": _absent_report(day),
    }


async def _page_context(
    db: AsyncSession,
    current_user: User,
    target: date,
    today: date,
) -> dict:
    is_manager = current_user.is_headman or current_user.is_admin
    day = await build_day(db, target, can_edit=is_manager, today=today)
    return {
        "current_user": current_user,
        "active_page": "attendance",
        **_day_context(day),
        "today_iso": today.isoformat(),
        "prev_date": (day.date - timedelta(days=1)).isoformat(),
        "next_date": (day.date + timedelta(days=1)).isoformat(),
        "date_label": (
            f"{DAY_NAMES[day.day_of_week]}, "
            f"{day.date.day} {MONTH_NAMES_GENITIVE[day.date.month]}"
        ),
        "is_manager": is_manager,
        "is_today": day.date == today,
        "is_future": day.date > today,
        "roster_text": "\n".join(
            student.full_name for student in day.students if student.is_active
        ),
    }


@router.get("", response_class=HTMLResponse)
async def attendance_page(
    request: Request,
    raw_date: str | None = Query(default=None, alias="date"),
    error: str | None = Query(default=None),
    current_user: User = Depends(get_current_user_web),
    db: AsyncSession = Depends(get_db),
):
    target = _parse_date(raw_date)
    today = get_current_date()
    context = await _page_context(db, current_user, target, today)
    context["error"] = ERROR_MESSAGES.get(error) if error else None
    return templates.TemplateResponse(
        request=request,
        name="attendance/index.html",
        context=context,
    )


@router.post("/{student_id}/mark", response_class=HTMLResponse)
async def mark_student(
    request: Request,
    student_id: int,
    raw_date: str = Query(alias="date"),
    status_value: AttendanceStatus = Query(alias="status"),
    current_user: User = Depends(get_current_headman_web),
    db: AsyncSession = Depends(get_db),
):
    target = _parse_date(raw_date)
    today = get_current_date()
    date_error = await mark_date_error(db, target, today)
    if date_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=date_error,
        )

    student = await get_active_student(db, student_id)
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ученик не найден",
        )

    await toggle_mark(db, target, student_id, status_value.value, current_user.id)
    await db.commit()

    day = await build_day(db, target, can_edit=True, today=today)
    marked_student = next(
        (item for item in day.students if item.id == student_id),
        None,
    )
    if marked_student is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ученик не найден",
        )

    return templates.TemplateResponse(
        request=request,
        name="attendance/student_row.html",
        context={
            "current_user": current_user,
            **_day_context(day),
            "student": marked_student,
            "include_row_parts": True,
        },
    )


@router.post("/fill-present")
async def fill_present(
    request: Request,
    current_user: User = Depends(get_current_headman_web),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    target = _parse_date(str(form.get("date", "") or "") or None)
    date_error = await mark_date_error(db, target, get_current_date())
    if date_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=date_error,
        )

    await mark_unmarked_present(db, target, current_user.id)
    await db.commit()

    if request.headers.get("HX-Request") != "true":
        return _redirect_day(target)

    day = await build_day(db, target, can_edit=True, today=get_current_date())
    return templates.TemplateResponse(
        request=request,
        name="attendance/list.html",
        context={
            "current_user": current_user,
            **_day_context(day),
            "oob_list": True,
            "oob_counts": True,
        },
    )


@router.post("/students")
async def save_roster(
    request: Request,
    current_user: User = Depends(get_current_headman_web),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    text = str(form.get("text", "") or "")
    target = _parse_date(str(form.get("date", "") or "") or None)

    try:
        await sync_roster(db, text)
    except RosterTextError as exc:
        return _redirect_day(target, error=str(exc))

    await db.commit()
    return _redirect_day(target)
