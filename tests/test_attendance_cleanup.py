from datetime import timedelta

import pytest
from sqlalchemy import select

from locus.attendance_cleanup import purge_archived_students, purge_old_attendance
from locus.constants import get_current_date
from locus.models.attendance import AttendanceRecord
from locus.models.student import Student


@pytest.mark.asyncio
async def test_old_attendance_is_purged(db_session):
    today = get_current_date()
    student = Student(full_name="Иванов Иван")
    db_session.add(student)
    await db_session.commit()
    await db_session.refresh(student)

    old = AttendanceRecord(
        student_id=student.id,
        attendance_date=today - timedelta(days=31),
        status="PRESENT",
    )
    edge = AttendanceRecord(
        student_id=student.id,
        attendance_date=today - timedelta(days=30),
        status="ABSENT",
    )
    fresh = AttendanceRecord(
        student_id=student.id,
        attendance_date=today,
        status="LATE",
    )
    db_session.add_all([old, edge, fresh])
    await db_session.commit()

    removed = await purge_old_attendance(db_session, 30)

    assert removed == 1
    dates = (
        (
            await db_session.execute(
                select(AttendanceRecord.attendance_date).order_by(
                    AttendanceRecord.attendance_date
                )
            )
        )
        .scalars()
        .all()
    )
    assert dates == [today - timedelta(days=30), today]


@pytest.mark.asyncio
async def test_archived_students_without_marks_are_purged(db_session):
    with_mark = Student(full_name="Архивный С Отметкой", is_active=False)
    without_mark = Student(full_name="Архивный Без Отметок", is_active=False)
    active = Student(full_name="Активный Ученик")
    db_session.add_all([with_mark, without_mark, active])
    await db_session.commit()
    for student in (with_mark, without_mark, active):
        await db_session.refresh(student)

    with_mark_id = with_mark.id
    without_mark_id = without_mark.id
    active_id = active.id

    db_session.add(
        AttendanceRecord(
            student_id=with_mark_id,
            attendance_date=get_current_date(),
            status="ABSENT",
        )
    )
    await db_session.commit()

    removed = await purge_archived_students(db_session)

    assert removed == 1
    db_session.expire_all()
    remaining_ids = set(
        (await db_session.execute(select(Student.id))).scalars().all()
    )
    assert without_mark_id not in remaining_ids
    assert with_mark_id in remaining_ids
    assert active_id in remaining_ids


@pytest.mark.asyncio
async def test_archived_student_is_removed_after_marks_expire(db_session):
    today = get_current_date()
    student = Student(full_name="Ушедший Ученик", is_active=False)
    db_session.add(student)
    await db_session.commit()
    await db_session.refresh(student)
    student_id = student.id

    db_session.add(
        AttendanceRecord(
            student_id=student_id,
            attendance_date=today - timedelta(days=31),
            status="PRESENT",
        )
    )
    await db_session.commit()

    assert await purge_old_attendance(db_session, 30) == 1
    assert await purge_archived_students(db_session) == 1

    db_session.expire_all()
    assert await db_session.get(Student, student_id) is None
