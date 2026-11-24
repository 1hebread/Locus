from datetime import date
from typing import Iterable

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from locus.constants import (
    ATTENDANCE_ABSENCE_STATUSES,
    AttendanceStatus,
    DAY_NAMES,
    get_current_date,
)
from locus.models.attendance import AttendanceRecord
from locus.models.student import Student
from locus.models.vacation import Vacation
from locus.schemas.attendance import (
    AttendanceCounts,
    AttendanceDayOut,
    AttendanceMarkIn,
    AttendanceStudentOut,
)
from locus.schemas.vacation import VacationOut

MAX_STUDENT_NAME_LENGTH = 255
MAX_ROSTER_TEXT_LENGTH = 20_000


class RosterTextError(ValueError):
    """Raised when the pasted class roster cannot be parsed."""


def parse_roster_text(text: str) -> list[str]:
    """Split a textarea into unique full names, preserving their order."""
    if len(text) > MAX_ROSTER_TEXT_LENGTH:
        raise RosterTextError("text_too_long")

    names: list[str] = []
    for raw_line in text.splitlines():
        name = " ".join(raw_line.split())
        if not name:
            continue
        if len(name) > MAX_STUDENT_NAME_LENGTH:
            raise RosterTextError("name_too_long")
        if name not in names:
            names.append(name)
    return names


async def sync_roster(db: AsyncSession, text: str) -> None:
    """Reconcile the class roster with textarea contents.

    Existing names keep their id (and attendance history); missing names are
    archived rather than deleted; archived names are reactivated if they return.
    """
    names = parse_roster_text(text)
    # shortcut: full names are encrypted (random ciphertext), so the DB cannot
    # enforce uniqueness; two simultaneous roster saves can insert the same
    # student twice. Add a deterministic name hash if multiple editors become common.
    result = await db.execute(select(Student))
    existing = {student.full_name: student for student in result.scalars().all()}

    for name in names:
        student = existing.get(name)
        if student:
            student.is_active = True
        else:
            db.add(Student(full_name=name))

    for name, student in existing.items():
        if name not in names:
            student.is_active = False


async def find_vacation(db: AsyncSession, target: date) -> Vacation | None:
    return (
        await db.execute(
            select(Vacation)
            .where(Vacation.start_date <= target, Vacation.end_date >= target)
            .order_by(Vacation.start_date)
            .limit(1)
        )
    ).scalars().first()


async def load_students_for_day(db: AsyncSession, target: date) -> list[Student]:
    """Active students plus archived ones with a mark on this date."""
    marked_student_ids = select(AttendanceRecord.student_id).where(
        AttendanceRecord.attendance_date == target
    )
    result = await db.execute(
        select(Student).where(
            or_(Student.is_active == True, Student.id.in_(marked_student_ids))
        )
    )
    # Full names are Fernet-encrypted, so SQL ordering would sort ciphertext.
    students = list(result.scalars().all())
    students.sort(key=lambda student: student.full_name.casefold())
    return students


async def load_statuses(db: AsyncSession, target: date) -> dict[int, str]:
    result = await db.execute(
        select(AttendanceRecord.student_id, AttendanceRecord.status).where(
            AttendanceRecord.attendance_date == target
        )
    )
    return dict(result.all())


async def build_day(
    db: AsyncSession,
    target: date,
    can_edit: bool,
    today: date | None = None,
) -> AttendanceDayOut:
    today = today or get_current_date()
    students = await load_students_for_day(db, target)
    statuses = await load_statuses(db, target)
    vacation = await find_vacation(db, target)

    is_school_day = target.isoweekday() <= 6 and vacation is None

    counts = {
        AttendanceStatus.PRESENT.value: 0,
        AttendanceStatus.ABSENT.value: 0,
        AttendanceStatus.LATE.value: 0,
        AttendanceStatus.EXCUSED.value: 0,
        AttendanceStatus.SICK.value: 0,
    }
    absence_values = {status.value for status in ATTENDANCE_ABSENCE_STATUSES}
    unmarked = 0
    for student in students:
        status = statuses.get(student.id)
        if status in absence_values:
            status = AttendanceStatus.ABSENT.value
        if status in counts:
            counts[status] += 1
        else:
            unmarked += 1

    return AttendanceDayOut(
        date=target,
        day_of_week=target.isoweekday(),
        day_name=DAY_NAMES[target.isoweekday()],
        is_school_day=is_school_day,
        is_editable=can_edit and is_school_day and target <= today,
        vacation=VacationOut.model_validate(vacation) if vacation else None,
        students=[
            AttendanceStudentOut(
                id=student.id,
                full_name=student.full_name,
                is_active=student.is_active,
                status=statuses.get(student.id),
            )
            for student in students
        ],
        counts=AttendanceCounts(
            present=counts[AttendanceStatus.PRESENT.value],
            absent=counts[AttendanceStatus.ABSENT.value],
            late=counts[AttendanceStatus.LATE.value],
            excused=counts[AttendanceStatus.EXCUSED.value],
            sick=counts[AttendanceStatus.SICK.value],
            unmarked=unmarked,
        ),
    )


async def mark_date_error(
    db: AsyncSession,
    target: date,
    today: date | None = None,
) -> str | None:
    """Return a human-readable reason why marks cannot be changed, if any."""
    today = today or get_current_date()
    if target > today:
        return "Нельзя отмечать посещаемость на будущую дату"
    if target.isoweekday() == 7:
        return "В воскресенье занятий нет"
    if await find_vacation(db, target):
        return "На эту дату приходятся каникулы"
    return None


async def get_active_student(db: AsyncSession, student_id: int) -> Student | None:
    return await db.scalar(
        select(Student).where(Student.id == student_id, Student.is_active == True)
    )


async def get_record(
    db: AsyncSession,
    target: date,
    student_id: int,
) -> AttendanceRecord | None:
    return await db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.attendance_date == target,
            AttendanceRecord.student_id == student_id,
        )
    )


async def set_mark(
    db: AsyncSession,
    target: date,
    student_id: int,
    status: str,
    marked_by_id: int,
) -> AttendanceRecord:
    record = await get_record(db, target, student_id)
    if record:
        record.status = status
        record.marked_by_id = marked_by_id
        return record

    try:
        async with db.begin_nested():
            record = AttendanceRecord(
                student_id=student_id,
                attendance_date=target,
                status=status,
                marked_by_id=marked_by_id,
            )
            db.add(record)
            await db.flush()
            return record
    except IntegrityError:
        record = await get_record(db, target, student_id)
        if record:
            record.status = status
            record.marked_by_id = marked_by_id
            return record
        raise


async def clear_mark(db: AsyncSession, target: date, student_id: int) -> bool:
    record = await get_record(db, target, student_id)
    if not record:
        return False
    await db.delete(record)
    return True


async def toggle_mark(
    db: AsyncSession,
    target: date,
    student_id: int,
    status: str,
    marked_by_id: int,
) -> AttendanceRecord | None:
    """Set a mark, or clear it when the same status is clicked again."""
    record = await get_record(db, target, student_id)
    if record and record.status == status:
        await db.delete(record)
        return None
    return await set_mark(db, target, student_id, status, marked_by_id)


async def apply_marks(
    db: AsyncSession,
    target: date,
    marks: Iterable[AttendanceMarkIn],
    marked_by_id: int,
) -> None:
    for mark in marks:
        if mark.status is None:
            await clear_mark(db, target, mark.student_id)
        else:
            await set_mark(db, target, mark.student_id, mark.status.value, marked_by_id)


async def mark_unmarked_present(
    db: AsyncSession,
    target: date,
    marked_by_id: int,
) -> int:
    """Set PRESENT for active students who have no mark on the date."""
    students = await load_students_for_day(db, target)
    statuses = await load_statuses(db, target)
    marked = 0
    for student in students:
        if student.is_active and student.id not in statuses:
            await set_mark(db, target, student.id, AttendanceStatus.PRESENT.value, marked_by_id)
            marked += 1
    return marked
