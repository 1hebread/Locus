from datetime import date

import re

import pytest
from sqlalchemy import func, select, text

from locus.config import get_settings
from locus.models.attendance import AttendanceRecord
from locus.models.student import Student
from locus.models.vacation import Vacation

TODAY = date(2026, 11, 24)  # Tuesday
PAST = date(2026, 11, 23)  # Monday
SUNDAY = date(2026, 11, 22)
FUTURE = date(2026, 11, 25)


@pytest.fixture
def fixed_today(monkeypatch) -> date:
    monkeypatch.setattr("locus.attendance.get_current_date", lambda: TODAY)
    monkeypatch.setattr("locus.api.attendance.get_current_date", lambda: TODAY)
    monkeypatch.setattr("locus.web.attendance_routes.get_current_date", lambda: TODAY)
    return TODAY


async def add_students(db_session, *names: str) -> list[Student]:
    students = [Student(full_name=name) for name in names]
    db_session.add_all(students)
    await db_session.commit()
    for student in students:
        await db_session.refresh(student)
    return students


def set_session_cookie(client, token: str) -> None:
    client.cookies.set(get_settings().COOKIE_NAME, token)


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attendance_api_requires_auth(client):
    res = await client.get("/api/v1/attendance")

    assert res.status_code == 401


@pytest.mark.asyncio
async def test_attendance_api_regular_user_reads(
    client, db_session, regular_auth_headers, fixed_today
):
    await add_students(db_session, "Петров Пётр", "Иванов Иван")

    res = await client.get("/api/v1/attendance", headers=regular_auth_headers)

    assert res.status_code == 200
    data = res.json()
    assert data["date"] == TODAY.isoformat()
    assert data["day_of_week"] == 2
    assert data["day_name"] == "Вторник"
    assert data["is_school_day"] is True
    assert data["is_editable"] is False
    assert data["vacation"] is None
    assert [student["full_name"] for student in data["students"]] == [
        "Иванов Иван",
        "Петров Пётр",
    ]
    assert all(student["status"] is None for student in data["students"])
    assert all(student["is_active"] is True for student in data["students"])
    assert data["counts"]["unmarked"] == 2

    res_past = await client.get(
        f"/api/v1/attendance?date={PAST.isoformat()}",
        headers=regular_auth_headers,
    )

    assert res_past.status_code == 200
    assert res_past.json()["date"] == PAST.isoformat()
    assert res_past.json()["day_name"] == "Понедельник"


@pytest.mark.asyncio
async def test_attendance_api_headman_marks_and_clears(
    client, db_session, headman_user, headman_auth_headers, fixed_today
):
    (student,) = await add_students(db_session, "Иванов Иван")
    url = f"/api/v1/attendance/{TODAY.isoformat()}"

    res = await client.put(
        url,
        json={"marks": [{"student_id": student.id, "status": "PRESENT"}]},
        headers=headman_auth_headers,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["students"][0]["status"] == "PRESENT"
    assert data["counts"]["present"] == 1
    assert data["is_editable"] is True

    record = await db_session.scalar(select(AttendanceRecord))
    assert record is not None
    assert record.status == "PRESENT"
    assert record.marked_by_id == headman_user.id

    res = await client.put(
        url,
        json={"marks": [{"student_id": student.id, "status": "LATE"}]},
        headers=headman_auth_headers,
    )

    assert res.status_code == 200
    assert res.json()["students"][0]["status"] == "LATE"
    assert (
        await db_session.scalar(select(func.count()).select_from(AttendanceRecord))
    ) == 1

    res = await client.put(
        url,
        json={"marks": [{"student_id": student.id, "status": None}]},
        headers=headman_auth_headers,
    )

    assert res.status_code == 200
    assert res.json()["students"][0]["status"] is None
    assert (
        await db_session.scalar(select(func.count()).select_from(AttendanceRecord))
    ) == 0


@pytest.mark.asyncio
async def test_attendance_api_admin_can_mark(
    client, db_session, auth_headers, fixed_today
):
    (student,) = await add_students(db_session, "Иванов Иван")

    res = await client.put(
        f"/api/v1/attendance/{TODAY.isoformat()}",
        json={"marks": [{"student_id": student.id, "status": "SICK"}]},
        headers=auth_headers,
    )

    assert res.status_code == 200
    assert res.json()["students"][0]["status"] == "SICK"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["ABSENT_UNKNOWN", "LEFT"])
async def test_attendance_api_absence_variants_count_as_absent(
    client, db_session, headman_auth_headers, fixed_today, status
):
    (student,) = await add_students(db_session, "Иванов Иван")

    res = await client.put(
        f"/api/v1/attendance/{TODAY.isoformat()}",
        json={"marks": [{"student_id": student.id, "status": status}]},
        headers=headman_auth_headers,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["students"][0]["status"] == status
    assert data["counts"]["absent"] == 1
    assert data["counts"]["unmarked"] == 0


@pytest.mark.asyncio
async def test_attendance_api_regular_user_cannot_mark(
    client, db_session, regular_auth_headers, fixed_today
):
    (student,) = await add_students(db_session, "Иванов Иван")

    res = await client.put(
        f"/api/v1/attendance/{TODAY.isoformat()}",
        json={"marks": [{"student_id": student.id, "status": "PRESENT"}]},
        headers=regular_auth_headers,
    )

    assert res.status_code == 403
    assert (
        await db_session.scalar(select(func.count()).select_from(AttendanceRecord))
    ) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target_date", "detail"),
    [
        (FUTURE, "Нельзя отмечать посещаемость на будущую дату"),
        (SUNDAY, "В воскресенье занятий нет"),
    ],
)
async def test_attendance_api_rejects_non_school_dates(
    client, headman_auth_headers, fixed_today, target_date, detail
):
    res = await client.put(
        f"/api/v1/attendance/{target_date.isoformat()}",
        json={"marks": []},
        headers=headman_auth_headers,
    )

    assert res.status_code == 400
    assert res.json()["detail"] == detail


@pytest.mark.asyncio
async def test_attendance_api_rejects_vacation(
    client, db_session, headman_auth_headers, fixed_today
):
    db_session.add(Vacation(name="Осенние", start_date=PAST, end_date=TODAY))
    await db_session.commit()

    res = await client.put(
        f"/api/v1/attendance/{TODAY.isoformat()}",
        json={"marks": []},
        headers=headman_auth_headers,
    )

    assert res.status_code == 400
    assert res.json()["detail"] == "На эту дату приходятся каникулы"


@pytest.mark.asyncio
async def test_attendance_api_vacation_is_read_only(
    client, db_session, headman_auth_headers, fixed_today
):
    db_session.add(Vacation(name="Осенние", start_date=PAST, end_date=TODAY))
    await db_session.commit()

    res = await client.get(
        f"/api/v1/attendance?date={TODAY.isoformat()}",
        headers=headman_auth_headers,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["is_school_day"] is False
    assert data["is_editable"] is False
    assert data["vacation"]["name"] == "Осенние"


@pytest.mark.asyncio
async def test_attendance_api_rejects_unknown_and_archived_students(
    client, db_session, headman_auth_headers, fixed_today
):
    active, archived = await add_students(db_session, "Активный Ученик", "Архивный Ученик")
    archived.is_active = False
    await db_session.commit()
    url = f"/api/v1/attendance/{TODAY.isoformat()}"

    for student_id in (archived.id, 999_999):
        res = await client.put(
            url,
            json={"marks": [{"student_id": student_id, "status": "PRESENT"}]},
            headers=headman_auth_headers,
        )

        assert res.status_code == 404
        assert res.json()["detail"] == "Ученик не найден"

    # One invalid id rejects the whole batch: the valid mark is not applied.
    res = await client.put(
        url,
        json={
            "marks": [
                {"student_id": active.id, "status": "PRESENT"},
                {"student_id": archived.id, "status": "ABSENT"},
            ]
        },
        headers=headman_auth_headers,
    )

    assert res.status_code == 404
    assert (
        await db_session.scalar(select(func.count()).select_from(AttendanceRecord))
    ) == 0


@pytest.mark.asyncio
async def test_attendance_api_validation_errors(
    client, db_session, headman_auth_headers, fixed_today
):
    (student,) = await add_students(db_session, "Иванов Иван")
    url = f"/api/v1/attendance/{TODAY.isoformat()}"

    payloads = [
        {"marks": [{"student_id": student.id, "status": "UNKNOWN"}]},
        {"marks": [{"student_id": student.id}]},
        {
            "marks": [
                {"student_id": student.id, "status": "PRESENT"},
                {"student_id": student.id, "status": "ABSENT"},
            ]
        },
        {
            "marks": [
                {"student_id": index + 1000, "status": "PRESENT"}
                for index in range(501)
            ]
        },
    ]

    for payload in payloads:
        res = await client.put(url, json=payload, headers=headman_auth_headers)
        assert res.status_code == 422

    assert (
        await db_session.scalar(select(func.count()).select_from(AttendanceRecord))
    ) == 0


@pytest.mark.asyncio
async def test_attendance_api_archived_student_history_visible(
    client, db_session, headman_auth_headers, regular_auth_headers, fixed_today
):
    active, archived = await add_students(
        db_session, "Активный Ученик", "Архивный Ученик"
    )

    res = await client.put(
        f"/api/v1/attendance/{PAST.isoformat()}",
        json={"marks": [{"student_id": archived.id, "status": "PRESENT"}]},
        headers=headman_auth_headers,
    )
    assert res.status_code == 200

    archived.is_active = False
    await db_session.commit()

    res_past = await client.get(
        f"/api/v1/attendance?date={PAST.isoformat()}",
        headers=regular_auth_headers,
    )
    assert res_past.status_code == 200
    past_students = res_past.json()["students"]
    assert [student["full_name"] for student in past_students] == [
        "Активный Ученик",
        "Архивный Ученик",
    ]
    archived_row = next(
        student for student in past_students if student["full_name"] == "Архивный Ученик"
    )
    assert archived_row["is_active"] is False
    assert archived_row["status"] == "PRESENT"

    res_today = await client.get(
        f"/api/v1/attendance?date={TODAY.isoformat()}",
        headers=regular_auth_headers,
    )
    assert [student["full_name"] for student in res_today.json()["students"]] == [
        "Активный Ученик"
    ]
    assert active.id != archived.id


# ---------------------------------------------------------------------------
# Web UI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attendance_student_names_are_encrypted_at_rest(
    client, db_session, headman_token, regular_auth_headers, fixed_today
):
    set_session_cookie(client, headman_token)

    res = await client.post(
        "/attendance/students",
        data={"text": "Иванов Иван", "date": TODAY.isoformat()},
        follow_redirects=False,
    )
    assert res.status_code == 303

    raw_name = (
        await db_session.execute(text("SELECT full_name FROM students"))
    ).scalar_one()
    assert raw_name.startswith("gAAAAA")
    assert "Иванов" not in raw_name

    api = await client.get(
        f"/api/v1/attendance?date={TODAY.isoformat()}",
        headers=regular_auth_headers,
    )
    assert api.status_code == 200
    assert api.json()["students"][0]["full_name"] == "Иванов Иван"


@pytest.mark.asyncio
async def test_attendance_web_requires_login(client):
    res = await client.get("/attendance", follow_redirects=False)

    assert res.status_code == 303
    assert res.headers["Location"] == "/login"


@pytest.mark.asyncio
async def test_attendance_web_regular_user_read_only(
    client, db_session, regular_token, fixed_today
):
    (student,) = await add_students(db_session, "Иванов Иван")
    set_session_cookie(client, regular_token)

    res = await client.get("/attendance")

    assert res.status_code == 200
    assert "Иванов Иван" in res.text
    assert "Не отмечен" in res.text
    assert f"/attendance/{student.id}/mark" not in res.text
    assert "Список класса" not in res.text
    assert "Только просмотр" in res.text
    assert "Остальные: Был" not in res.text


@pytest.mark.asyncio
async def test_attendance_web_headman_sees_controls(
    client, db_session, headman_token, fixed_today
):
    (student,) = await add_students(db_session, "Иванов Иван")
    set_session_cookie(client, headman_token)

    res = await client.get("/attendance")

    assert res.status_code == 200
    assert f"/attendance/{student.id}/mark" in res.text
    assert "Список класса" in res.text
    assert 'hx-disabled-elt="this"' in res.text
    assert 'hx-target="closest [data-attendance-row]"' in res.text
    assert "Неизвестно" in res.text
    assert "Ушёл" in res.text
    assert "data-split-menu" in res.text
    assert "Остальные: Был" in res.text
    assert 'data-attendance-filter="present"' in res.text
    assert 'data-absent-statuses="ABSENT,ABSENT_UNKNOWN,LEFT"' in res.text


@pytest.mark.asyncio
async def test_attendance_web_toggle_mark(
    client, db_session, headman_user, headman_token, fixed_today
):
    (student,) = await add_students(db_session, "Иванов Иван")
    set_session_cookie(client, headman_token)
    url = f"/attendance/{student.id}/mark?date={TODAY.isoformat()}&status=PRESENT"

    res = await client.post(url)

    assert res.status_code == 200
    assert 'hx-swap-oob="outerHTML"' in res.text
    assert 'id="attendance-list-actions"' in res.text
    assert "border-accent-line/80 bg-accent/25 text-accent-ink" in res.text
    record = await db_session.scalar(select(AttendanceRecord))
    assert record is not None
    assert record.status == "PRESENT"
    assert record.marked_by_id == headman_user.id

    res = await client.post(url)

    assert res.status_code == 200
    assert "border-accent-line/80 bg-accent/25 text-accent-ink" not in res.text
    assert (
        await db_session.scalar(select(func.count()).select_from(AttendanceRecord))
    ) == 0


@pytest.mark.asyncio
async def test_attendance_web_fill_present_marks_only_unmarked(
    client, db_session, headman_user, headman_token, fixed_today
):
    present, unmarked, archived = await add_students(
        db_session, "Первый Ученик", "Второй Ученик", "Архивный Ученик"
    )
    archived.is_active = False
    db_session.add(
        AttendanceRecord(
            student_id=present.id,
            attendance_date=TODAY,
            status="LATE",
            marked_by_id=headman_user.id,
        )
    )
    await db_session.commit()
    set_session_cookie(client, headman_token)

    res = await client.post(
        "/attendance/fill-present",
        data={"date": TODAY.isoformat()},
        follow_redirects=False,
    )

    assert res.status_code == 303
    assert res.headers["Location"] == f"/attendance?date={TODAY.isoformat()}"

    present_id, unmarked_id, archived_id = present.id, unmarked.id, archived.id
    db_session.expire_all()
    records = (await db_session.execute(select(AttendanceRecord))).scalars().all()
    statuses = {record.student_id: record.status for record in records}
    assert statuses[present_id] == "LATE"
    assert statuses[unmarked_id] == "PRESENT"
    assert archived_id not in statuses


@pytest.mark.asyncio
async def test_attendance_web_fill_present_htmx_updates_in_place(
    client, db_session, headman_user, headman_token, fixed_today
):
    unmarked, absent = await add_students(db_session, "Первый Ученик", "Второй Ученик")
    unmarked_id, absent_id = unmarked.id, absent.id
    db_session.add(
        AttendanceRecord(
            student_id=absent_id,
            attendance_date=TODAY,
            status="ABSENT",
            marked_by_id=headman_user.id,
        )
    )
    await db_session.commit()
    set_session_cookie(client, headman_token)

    res = await client.post(
        "/attendance/fill-present",
        data={"date": TODAY.isoformat()},
        headers={"HX-Request": "true"},
        follow_redirects=False,
    )

    assert res.status_code == 200
    assert 'id="attendance-list"' in res.text
    assert 'hx-swap-oob="outerHTML"' in res.text
    assert 'hx-post="/attendance/fill-present"' not in res.text

    db_session.expire_all()
    records = (await db_session.execute(select(AttendanceRecord))).scalars().all()
    statuses = {record.student_id: record.status for record in records}
    assert statuses[unmarked_id] == "PRESENT"
    assert statuses[absent_id] == "ABSENT"


@pytest.mark.asyncio
async def test_attendance_web_absent_copy_report(
    client, db_session, headman_user, headman_token, fixed_today
):
    sick, unknown, present = await add_students(
        db_session, "Иванов Иван", "Петров Пётр", "Сидоров Сидор"
    )
    for student, status in (
        (sick, "SICK"),
        (unknown, "ABSENT_UNKNOWN"),
        (present, "PRESENT"),
    ):
        db_session.add(
            AttendanceRecord(
                student_id=student.id,
                attendance_date=TODAY,
                status=status,
                marked_by_id=headman_user.id,
            )
        )
    await db_session.commit()
    set_session_cookie(client, headman_token)

    res = await client.get("/attendance")

    report = re.search(r'data-copy-text="(.*?)"', res.text, re.S)
    assert report is not None
    assert report.group(1) == "Иванов Иван — болеет\nПетров Пётр — неизвестно"


@pytest.mark.asyncio
async def test_attendance_web_regular_user_cannot_mark(
    client, db_session, regular_token, fixed_today
):
    (student,) = await add_students(db_session, "Иванов Иван")
    set_session_cookie(client, regular_token)

    res = await client.post(
        f"/attendance/{student.id}/mark?date={TODAY.isoformat()}&status=PRESENT"
    )

    assert res.status_code == 403
    assert (
        await db_session.scalar(select(func.count()).select_from(AttendanceRecord))
    ) == 0


@pytest.mark.asyncio
async def test_attendance_web_roster_sync(
    client, db_session, headman_token, fixed_today
):
    set_session_cookie(client, headman_token)

    res = await client.post(
        "/attendance/students",
        data={"text": "Иванов Иван\nПетров Пётр", "date": TODAY.isoformat()},
        follow_redirects=False,
    )

    assert res.status_code == 303
    assert res.headers["Location"] == f"/attendance?date={TODAY.isoformat()}"

    students = sorted(
        (await db_session.execute(select(Student))).scalars().all(),
        key=lambda student: student.full_name.casefold(),
    )
    assert [student.full_name for student in students] == ["Иванов Иван", "Петров Пётр"]
    assert all(student.is_active for student in students)
    petrov_id = students[1].id

    res = await client.post(
        "/attendance/students",
        data={"text": "Иванов Иван", "date": TODAY.isoformat()},
        follow_redirects=False,
    )

    assert res.status_code == 303
    db_session.expire_all()
    petrov = await db_session.get(Student, petrov_id)
    assert petrov.is_active is False

    res = await client.post(
        "/attendance/students",
        data={"text": "Иванов Иван\nПетров Пётр", "date": TODAY.isoformat()},
        follow_redirects=False,
    )

    assert res.status_code == 303
    db_session.expire_all()
    petrov = await db_session.get(Student, petrov_id)
    assert petrov.is_active is True


@pytest.mark.asyncio
async def test_attendance_web_empty_roster_archives_all(
    client, db_session, headman_token, fixed_today
):
    await add_students(db_session, "Иванов Иван", "Петров Пётр")
    set_session_cookie(client, headman_token)

    res = await client.post(
        "/attendance/students",
        data={"text": "", "date": TODAY.isoformat()},
        follow_redirects=False,
    )

    assert res.status_code == 303
    db_session.expire_all()
    students = (await db_session.execute(select(Student))).scalars().all()
    assert all(student.is_active is False for student in students)

    page = await client.get("/attendance")
    assert "Список класса пуст" in page.text


@pytest.mark.asyncio
async def test_attendance_web_archived_student_visible_on_past_date(
    client, db_session, headman_user, headman_token, fixed_today
):
    _, archived = await add_students(db_session, "Активный Ученик", "Архивный Ученик")
    db_session.add(
        AttendanceRecord(
            student_id=archived.id,
            attendance_date=PAST,
            status="PRESENT",
            marked_by_id=headman_user.id,
        )
    )
    archived.is_active = False
    await db_session.commit()
    set_session_cookie(client, headman_token)

    past_page = await client.get(f"/attendance?date={PAST.isoformat()}")
    assert "Архивный Ученик" in past_page.text
    assert "Архив" in past_page.text

    today_page = await client.get(f"/attendance?date={TODAY.isoformat()}")
    assert "Архивный Ученик" not in today_page.text


@pytest.mark.asyncio
async def test_attendance_web_invalid_date(client, regular_token):
    set_session_cookie(client, regular_token)

    res = await client.get("/attendance?date=not-a-date")

    assert res.status_code == 400
    assert res.json()["detail"] == "Некорректная дата"


@pytest.mark.asyncio
async def test_attendance_web_roster_validation_errors(
    client, db_session, headman_token, fixed_today
):
    set_session_cookie(client, headman_token)

    res = await client.post(
        "/attendance/students",
        data={"text": "А" * 256, "date": TODAY.isoformat()},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert "error=name_too_long" in res.headers["Location"]

    res = await client.post(
        "/attendance/students",
        data={"text": "x" * 20_001, "date": TODAY.isoformat()},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert "error=text_too_long" in res.headers["Location"]

    page = await client.get("/attendance?error=name_too_long")
    assert "Слишком длинное имя ученика" in page.text

    assert (
        await db_session.scalar(select(func.count()).select_from(Student))
    ) == 0


@pytest.mark.asyncio
async def test_attendance_web_regular_user_cannot_edit_roster(
    client, db_session, regular_token, fixed_today
):
    set_session_cookie(client, regular_token)

    res = await client.post(
        "/attendance/students",
        data={"text": "Иванов Иван", "date": TODAY.isoformat()},
    )

    assert res.status_code == 403
    assert (
        await db_session.scalar(select(func.count()).select_from(Student))
    ) == 0
