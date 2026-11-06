import pytest
from httpx import AsyncClient
from sqlalchemy import text

from locus.models.subject import Subject


@pytest.mark.asyncio
async def test_subject_crud(client: AsyncClient, auth_headers: dict):
    # Create subject
    res_create = await client.post(
        "/api/v1/subjects",
        headers=auth_headers,
        json={
            "name": "Физика",
            "teacher_name": "Петров В.В.",
            "room": "201",
        },
    )
    assert res_create.status_code == 201
    subj_data = res_create.json()
    assert subj_data["name"] == "Физика"
    subj_id = subj_data["id"]

    # List subjects
    res_list = await client.get("/api/v1/subjects", headers=auth_headers)
    assert res_list.status_code == 200
    assert any(s["id"] == subj_id for s in res_list.json())

    # Update subject
    res_update = await client.put(
        f"/api/v1/subjects/{subj_id}",
        headers=auth_headers,
        json={"room": "205"},
    )
    assert res_update.status_code == 200
    assert res_update.json()["room"] == "205"

    # Delete subject
    res_delete = await client.delete(f"/api/v1/subjects/{subj_id}", headers=auth_headers)
    assert res_delete.status_code == 204


@pytest.mark.asyncio
async def test_non_admin_can_view_but_not_change_subjects_and_schedule(
    client: AsyncClient,
    auth_headers: dict,
    regular_auth_headers: dict,
    test_subject: Subject,
):
    list_subjects = await client.get("/api/v1/subjects", headers=regular_auth_headers)
    assert list_subjects.status_code == 200
    assert any(s["id"] == test_subject.id for s in list_subjects.json())

    list_schedule = await client.get("/api/v1/schedule", headers=regular_auth_headers)
    assert list_schedule.status_code == 200

    create_subject = await client.post(
        "/api/v1/subjects",
        headers=regular_auth_headers,
        json={"name": "Запрещённый предмет"},
    )
    assert create_subject.status_code == 403

    create_lesson = await client.post(
        "/api/v1/schedule",
        headers=regular_auth_headers,
        json={
            "subject_id": test_subject.id,
            "day_of_week": 1,
            "lesson_number": 1,
            "week_type": "ALL",
        },
    )
    assert create_lesson.status_code == 403

    admin_lesson = await client.post(
        "/api/v1/schedule",
        headers=auth_headers,
        json={
            "subject_id": test_subject.id,
            "day_of_week": 1,
            "lesson_number": 1,
            "week_type": "ALL",
        },
    )
    assert admin_lesson.status_code == 201
    lesson_id = admin_lesson.json()["id"]

    update_lesson = await client.put(
        f"/api/v1/schedule/{lesson_id}",
        headers=regular_auth_headers,
        json={"room": "999"},
    )
    assert update_lesson.status_code == 403

    delete_subject = await client.delete(
        f"/api/v1/subjects/{test_subject.id}",
        headers=regular_auth_headers,
    )
    assert delete_subject.status_code == 403


@pytest.mark.asyncio
async def test_lesson_with_default_bell_times(
    client: AsyncClient,
    auth_headers: dict,
    test_subject: Subject,
):
    """If start_time and end_time are omitted, schema auto-fills school bell times."""
    res = await client.post(
        "/api/v1/schedule",
        headers=auth_headers,
        json={
            "subject_id": test_subject.id,
            "day_of_week": 1,  # Monday
            "lesson_number": 1,
            "week_type": "ALL",
        },
    )
    assert res.status_code == 201
    data = res.json()
    # 1st lesson default: 08:00 - 08:45
    assert data["start_time"] == "08:00"
    assert data["end_time"] == "08:45"
    assert data["subject"]["name"] == test_subject.name

    # 2nd lesson default with 5 min break: 08:50 - 09:35
    res2 = await client.post(
        "/api/v1/schedule",
        headers=auth_headers,
        json={
            "subject_id": test_subject.id,
            "day_of_week": 1,
            "lesson_number": 2,
            "week_type": "ALL",
        },
    )
    assert res2.status_code == 201
    data2 = res2.json()
    assert data2["start_time"] == "08:50"
    assert data2["end_time"] == "09:35"


@pytest.mark.asyncio
async def test_lesson_with_custom_times_and_filtering(
    client: AsyncClient,
    auth_headers: dict,
    test_subject: Subject,
):
    """Test custom times and week_type filtering."""
    # Lesson 1: Numerator week
    res1 = await client.post(
        "/api/v1/schedule",
        headers=auth_headers,
        json={
            "subject_id": test_subject.id,
            "day_of_week": 2,  # Tuesday
            "lesson_number": 2,
            "start_time": "09:30",
            "end_time": "10:15",
            "week_type": "NUMERATOR",
        },
    )
    assert res1.status_code == 201

    # Lesson 2: Denominator week
    res2 = await client.post(
        "/api/v1/schedule",
        headers=auth_headers,
        json={
            "subject_id": test_subject.id,
            "day_of_week": 2,
            "lesson_number": 3,
            "week_type": "DENOMINATOR",
        },
    )
    assert res2.status_code == 201

    # Query for NUMERATOR week -> should include NUMERATOR and ALL, not DENOMINATOR
    res_num = await client.get(
        "/api/v1/schedule?day_of_week=2&week_type=NUMERATOR",
        headers=auth_headers,
    )
    assert res_num.status_code == 200
    items = res_num.json()
    assert len(items) == 1
    assert items[0]["week_type"] == "NUMERATOR"
    assert items[0]["start_time"] == "09:30"


@pytest.mark.asyncio
async def test_subject_teacher_phone_encryption_and_whatsapp(
    client: AsyncClient,
    auth_headers: dict,
    db_session,
    auth_token: str,
):
    from sqlalchemy import text
    from locus.config import get_settings

    settings = get_settings()

    # 1. Create subject via REST API with teacher phone
    res_create = await client.post(
        "/api/v1/subjects",
        headers=auth_headers,
        json={
            "name": "Информатика",
            "teacher_name": "Сергеев С.С.",
            "teacher_phone": "+7 (999) 111-22-33",
            "room": "101",
        },
    )
    assert res_create.status_code == 201
    subj_data = res_create.json()
    assert subj_data["teacher_phone"] == "+7 (999) 111-22-33"
    assert subj_data["whatsapp_url"] == "https://wa.me/79991112233"
    subj_id = subj_data["id"]

    # 2. Check raw DB row to confirm encryption at rest for both teacher_phone and teacher_name
    raw_res = await db_session.execute(
        text("SELECT teacher_phone, teacher_name FROM subjects WHERE id = :id"),
        {"id": subj_id},
    )
    raw_val, raw_name = raw_res.one()
    assert raw_val is not None
    assert raw_val.startswith("gAAAAA")
    assert "999" not in raw_val
    assert "111-22-33" not in raw_val

    assert raw_name is not None
    assert raw_name.startswith("gAAAAA")
    assert "Сергеев" not in raw_name

    # 3. Web subjects page displays phone and WhatsApp link
    client.cookies.set(settings.COOKIE_NAME, auth_token)
    res_page = await client.get("/subjects")
    assert res_page.status_code == 200
    assert "+7 (999) 111-22-33" in res_page.text
    assert "https://wa.me/79991112233" in res_page.text

    # 4. Web edit subject updates phone
    res_edit = await client.post(
        f"/subjects/{subj_id}/edit",
        data={
            "name": "Информатика углубленная",
            "teacher_name": "Сергеев С.С.",
            "teacher_phone": "8 (999) 555-66-77",
            "room": "102",
        },
        follow_redirects=False,
    )
    assert res_edit.status_code == 303

    # Check updated values
    res_get = await client.get(f"/api/v1/subjects/{subj_id}", headers=auth_headers)
    assert res_get.status_code == 200
    assert res_get.json()["teacher_phone"] == "8 (999) 555-66-77"
    assert res_get.json()["whatsapp_url"] == "https://wa.me/79995556677"

    # Raw DB row is still encrypted
    raw_res2 = await db_session.execute(
        text("SELECT teacher_phone, teacher_name FROM subjects WHERE id = :id"),
        {"id": subj_id},
    )
    raw_val2, raw_name2 = raw_res2.one()
    assert raw_val2.startswith("gAAAAA")
    assert "555" not in raw_val2
    assert raw_name2.startswith("gAAAAA")
    assert "Сергеев" not in raw_name2

    # 5. 10-digit and 11-digit phone normalization
    res_ten = await client.post(
        f"/subjects/{subj_id}/edit",
        data={
            "name": "Информатика",
            "teacher_phone": "9991234567",
        },
        follow_redirects=False,
    )
    assert res_ten.status_code == 303
    res_get_ten = await client.get(f"/api/v1/subjects/{subj_id}", headers=auth_headers)
    assert res_get_ten.json()["whatsapp_url"] == "https://wa.me/79991234567"

    # 5.1. International phone starting with +8 retains country code
    res_intl = await client.post(
        f"/subjects/{subj_id}/edit",
        data={
            "name": "Информатика",
            "teacher_phone": "+85512345678",
        },
        follow_redirects=False,
    )
    assert res_intl.status_code == 303
    res_get_intl = await client.get(f"/api/v1/subjects/{subj_id}", headers=auth_headers)
    assert res_get_intl.json()["whatsapp_url"] == "https://wa.me/85512345678"

    # 5.2. Typing invalid phone with letters preserves existing valid phone
    res_bad = await client.post(
        f"/subjects/{subj_id}/edit",
        data={
            "name": "Информатика",
            "teacher_phone": "invalid_letters",
        },
        follow_redirects=False,
    )
    assert res_bad.status_code == 303
    res_get_bad = await client.get(f"/api/v1/subjects/{subj_id}", headers=auth_headers)
    assert res_get_bad.json()["teacher_phone"] == "+85512345678"

    # 6. Whitespace-only phone clears to None
    res_clear = await client.post(
        f"/subjects/{subj_id}/edit",
        data={
            "name": "Информатика",
            "teacher_phone": "   ",
            "teacher_name": "   ",
        },
        follow_redirects=False,
    )
    assert res_clear.status_code == 303
    res_get_clear = await client.get(f"/api/v1/subjects/{subj_id}", headers=auth_headers)
    assert res_get_clear.json()["teacher_phone"] is None
    assert res_get_clear.json()["teacher_name"] is None
    assert res_get_clear.json()["whatsapp_url"] is None

    # 7. Apostrophes and quotes in data-* attributes
    res_quotes = await client.post(
        f"/subjects/{subj_id}/edit",
        data={
            "name": "English O'Connor",
            "teacher_name": "Д'Артаньян",
        },
        follow_redirects=False,
    )
    assert res_quotes.status_code == 303
    res_page_quotes = await client.get("/subjects")
    assert 'data-name="English O&#39;Connor"' in res_page_quotes.text or "data-name=\"English O'Connor\"" in res_page_quotes.text
    assert "onclick=\"openEditSubjectModal(this)\"" in res_page_quotes.text


@pytest.mark.asyncio
async def test_vacation_api_crud_and_validation(
    client: AsyncClient,
    auth_headers: dict,
    regular_auth_headers: dict,
):
    # 1. Non-admin cannot create vacation
    res_forbidden = await client.post(
        "/api/v1/vacations",
        headers=regular_auth_headers,
        json={
            "name": "Осенние каникулы",
            "start_date": "2026-10-26",
            "end_date": "2026-11-03",
        },
    )
    assert res_forbidden.status_code == 403

    # 2. Validation: start_date > end_date returns 422, whitespace-only name returns 422
    res_invalid = await client.post(
        "/api/v1/vacations",
        headers=auth_headers,
        json={
            "name": "Неверные каникулы",
            "start_date": "2026-11-10",
            "end_date": "2026-11-01",
        },
    )
    assert res_invalid.status_code == 422

    res_whitespace = await client.post(
        "/api/v1/vacations",
        headers=auth_headers,
        json={
            "name": "    ",
            "start_date": "2026-10-26",
            "end_date": "2026-11-01",
        },
    )
    assert res_whitespace.status_code == 422

    # 3. Admin creates vacation
    res_create = await client.post(
        "/api/v1/vacations",
        headers=auth_headers,
        json={
            "name": "Осенние каникулы",
            "start_date": "2026-10-26",
            "end_date": "2026-11-03",
        },
    )
    assert res_create.status_code == 201
    vac_data = res_create.json()
    assert vac_data["name"] == "Осенние каникулы"
    assert vac_data["start_date"] == "2026-10-26"
    assert vac_data["end_date"] == "2026-11-03"
    vac_id = vac_data["id"]

    # 3.1. Overlapping vacation rejected with 422
    res_overlap = await client.post(
        "/api/v1/vacations",
        headers=auth_headers,
        json={
            "name": "Вторые осенние",
            "start_date": "2026-10-30",
            "end_date": "2026-11-05",
        },
    )
    assert res_overlap.status_code == 422
    assert "пересекаются" in res_overlap.json()["detail"]

    # 4. Regular user can view vacations
    res_list = await client.get("/api/v1/vacations", headers=regular_auth_headers)
    assert res_list.status_code == 200
    assert any(v["id"] == vac_id for v in res_list.json())

    # 5. Get single vacation
    res_get = await client.get(f"/api/v1/vacations/{vac_id}", headers=regular_auth_headers)
    assert res_get.status_code == 200
    assert res_get.json()["name"] == "Осенние каникулы"

    # 6. Admin updates vacation
    res_update = await client.put(
        f"/api/v1/vacations/{vac_id}",
        headers=auth_headers,
        json={"name": "Большие осенние каникулы"},
    )
    assert res_update.status_code == 200
    assert res_update.json()["name"] == "Большие осенние каникулы"

    # 7. Non-admin cannot delete
    res_del_forbidden = await client.delete(
        f"/api/v1/vacations/{vac_id}",
        headers=regular_auth_headers,
    )
    assert res_del_forbidden.status_code == 403

    # 8. Admin deletes vacation
    res_delete = await client.delete(
        f"/api/v1/vacations/{vac_id}",
        headers=auth_headers,
    )
    assert res_delete.status_code == 204

    # 9. Verify deleted
    res_get_deleted = await client.get(f"/api/v1/vacations/{vac_id}", headers=auth_headers)
    assert res_get_deleted.status_code == 404


@pytest.mark.asyncio
async def test_teacher_name_encryption_multibyte_and_legacy_fallback(
    client: AsyncClient,
    auth_headers: dict,
    db_session,
):
    """Test multi-byte UTF-8 emoji support and legacy unencrypted fallback for teacher_name."""
    # 1. Create subject with emoji in teacher name
    res_create = await client.post(
        "/api/v1/subjects",
        headers=auth_headers,
        json={
            "name": "Астрономия",
            "teacher_name": "Ковалевская С.В. 👩‍🏫🔭",
            "teacher_phone": "+7 999 111-22-33",
            "room": "305",
        },
    )
    assert res_create.status_code == 201
    subj_id = res_create.json()["id"]
    assert res_create.json()["teacher_name"] == "Ковалевская С.В. 👩‍🏫🔭"

    # 2. Raw database check: encrypted at rest
    raw_res = await db_session.execute(
        text("SELECT teacher_name FROM subjects WHERE id = :id"),
        {"id": subj_id},
    )
    raw_name = raw_res.scalar_one()
    assert raw_name.startswith("gAAAAA")
    assert "Ковалевская" not in raw_name

    # 3. Insert legacy unencrypted row directly with raw SQL
    await db_session.execute(
        text("INSERT INTO subjects (name, teacher_name, room) VALUES (:name, :teacher, :room)"),
        {"name": "Краеведение", "teacher": "Петров Станислав (legacy)", "room": "201"},
    )
    await db_session.commit()

    # 4. Fetch via API: legacy unencrypted name is safely read as plaintext
    res_list = await client.get("/api/v1/subjects", headers=auth_headers)
    assert res_list.status_code == 200
    legacy_subj = next(s for s in res_list.json() if s["name"] == "Краеведение")
    assert legacy_subj["teacher_name"] == "Петров Станислав (legacy)"


@pytest.mark.asyncio
async def test_lesson_duplicate_number_and_overlapping_time_rejected_via_api(
    client: AsyncClient,
    auth_headers: dict,
    test_subject: Subject,
):
    # 1. Create first lesson on Monday (lesson_number=1, default time 08:00–08:45)
    res1 = await client.post(
        "/api/v1/schedule",
        headers=auth_headers,
        json={
            "subject_id": test_subject.id,
            "day_of_week": 1,
            "lesson_number": 1,
            "start_time": "08:00",
            "end_time": "08:45",
        },
    )
    assert res1.status_code == 201
    lesson1_id = res1.json()["id"]

    # 2. Duplicate lesson_number on same day rejected
    res_dup = await client.post(
        "/api/v1/schedule",
        headers=auth_headers,
        json={
            "subject_id": test_subject.id,
            "day_of_week": 1,
            "lesson_number": 1,
            "start_time": "09:00",
            "end_time": "09:45",
        },
    )
    assert res_dup.status_code == 422
    assert "Урок №1 в этот день уже существует" in res_dup.json()["detail"]

    # 3. Overlapping time on same day rejected (different lesson number, but overlapping time 08:30–09:15)
    res_overlap = await client.post(
        "/api/v1/schedule",
        headers=auth_headers,
        json={
            "subject_id": test_subject.id,
            "day_of_week": 1,
            "lesson_number": 2,
            "start_time": "08:30",
            "end_time": "09:15",
        },
    )
    assert res_overlap.status_code == 422
    assert "пересекается с уроком №1" in res_overlap.json()["detail"]

    # 4. Same time interval on same day rejected (exact match 08:00–08:45)
    res_same_time = await client.post(
        "/api/v1/schedule",
        headers=auth_headers,
        json={
            "subject_id": test_subject.id,
            "day_of_week": 1,
            "lesson_number": 3,
            "start_time": "08:00",
            "end_time": "08:45",
        },
    )
    assert res_same_time.status_code == 422
    assert "пересекается с уроком №1" in res_same_time.json()["detail"]

    # 5. Invalid time interval (start_time >= end_time) rejected
    res_invalid_time = await client.post(
        "/api/v1/schedule",
        headers=auth_headers,
        json={
            "subject_id": test_subject.id,
            "day_of_week": 1,
            "lesson_number": 2,
            "start_time": "09:45",
            "end_time": "09:00",
        },
    )
    assert res_invalid_time.status_code == 422
    assert "Время окончания урока должно быть позже времени начала" in res_invalid_time.text

    # 6. Valid non-overlapping lesson 2 on same day succeeds
    res2 = await client.post(
        "/api/v1/schedule",
        headers=auth_headers,
        json={
            "subject_id": test_subject.id,
            "day_of_week": 1,
            "lesson_number": 2,
            "start_time": "08:55",
            "end_time": "09:40",
        },
    )
    assert res2.status_code == 201

    # 7. Updating lesson without conflicting with itself succeeds
    res_update_self = await client.put(
        f"/api/v1/schedule/{lesson1_id}",
        headers=auth_headers,
        json={"room": "303"},
    )
    assert res_update_self.status_code == 200
    assert res_update_self.json()["room"] == "303"

    # 8. Updating lesson to conflict with lesson 2 rejected
    res_update_conflict = await client.put(
        f"/api/v1/schedule/{lesson1_id}",
        headers=auth_headers,
        json={"lesson_number": 2},
    )
    assert res_update_conflict.status_code == 422
    assert "Урок №2 в этот день уже существует" in res_update_conflict.json()["detail"]

    # 9. Same lesson number on DIFFERENT day (Tuesday) succeeds
    res_tuesday = await client.post(
        "/api/v1/schedule",
        headers=auth_headers,
        json={
            "subject_id": test_subject.id,
            "day_of_week": 2,
            "lesson_number": 1,
            "start_time": "08:00",
            "end_time": "08:45",
        },
    )
    assert res_tuesday.status_code == 201

    # 10. Partial update of start_time only exceeding existing end_time rejected
    res_partial_bad_time = await client.put(
        f"/api/v1/schedule/{lesson1_id}",
        headers=auth_headers,
        json={"start_time": "08:50"},
    )
    assert res_partial_bad_time.status_code == 422
    assert "Время окончания урока должно быть позже времени начала" in res_partial_bad_time.text

    # 11. Partial update of start_time colliding with lesson 2 rejected
    res_partial_overlap = await client.put(
        f"/api/v1/schedule/{lesson1_id}",
        headers=auth_headers,
        json={"start_time": "08:40", "end_time": "09:05"},
    )
    assert res_partial_overlap.status_code == 422
    assert "пересекается с уроком №2" in res_partial_overlap.json()["detail"]

    # 12. Updating with explicit null for required fields rejected with 422
    res_null_time = await client.put(
        f"/api/v1/schedule/{lesson1_id}",
        headers=auth_headers,
        json={"start_time": None},
    )
    assert res_null_time.status_code == 422
    assert "не может быть пустым" in res_null_time.text

    res_null_num = await client.put(
        f"/api/v1/schedule/{lesson1_id}",
        headers=auth_headers,
        json={"lesson_number": None},
    )
    assert res_null_num.status_code == 422
    assert "не может быть пустым" in res_null_num.text


@pytest.mark.asyncio
async def test_clone_lesson_api(
    client: AsyncClient,
    auth_headers: dict,
    regular_auth_headers: dict,
    test_subject: Subject,
):
    """Test cloning a lesson with the other subgroup."""
    subj_id = test_subject.id

    # 1. Create a lesson with subgroup 1 on Thursday
    create_res = await client.post(
        "/api/v1/schedule",
        headers=auth_headers,
        json={
            "subject_id": subj_id,
            "day_of_week": 4,
            "lesson_number": 1,
            "start_time": "08:00",
            "end_time": "08:45",
            "subgroup": 1,
            "room": "101",
            "note": "Подгруппа А",
        },
    )
    assert create_res.status_code == 201
    lesson1_id = create_res.json()["id"]

    # 2. Non-admin cannot clone
    res_forbidden = await client.post(
        f"/api/v1/schedule/{lesson1_id}/clone",
        headers=regular_auth_headers,
    )
    assert res_forbidden.status_code == 403

    # 3. Admin clones lesson 1 -> creates counterpart for subgroup 2
    # Since test_subject has no room2 configured, room for subgroup 2 is None (not copied from subgroup 1)
    clone_res = await client.post(
        f"/api/v1/schedule/{lesson1_id}/clone",
        headers=auth_headers,
    )
    assert clone_res.status_code == 201
    cloned_data = clone_res.json()
    assert cloned_data["id"] != lesson1_id
    assert str(cloned_data["subgroup"]) == "2"
    assert cloned_data["lesson_number"] == 1
    assert cloned_data["day_of_week"] == 4
    assert cloned_data["start_time"] == "08:00"
    assert cloned_data["end_time"] == "08:45"
    assert cloned_data["room"] is None
    assert cloned_data["note"] == "Подгруппа А"

    # 4. Cloning again fails because subgroup 2 already exists
    clone_again = await client.post(
        f"/api/v1/schedule/{lesson1_id}/clone",
        headers=auth_headers,
    )
    assert clone_again.status_code == 422
    assert "уже существует" in clone_again.json()["detail"]

    # 5. Clone whole-class lesson (subgroup=None) with attached homework:
    # splits into sub 1 and sub 2, and duplicates homework
    whole_res = await client.post(
        "/api/v1/schedule",
        headers=auth_headers,
        json={
            "subject_id": subj_id,
            "day_of_week": 4,
            "lesson_number": 2,
            "start_time": "08:50",
            "end_time": "09:35",
            "subgroup": None,
        },
    )
    assert whole_res.status_code == 201
    whole_id = whole_res.json()["id"]

    # Add homework attached to this whole-class lesson
    from datetime import date, timedelta
    due_date = date.today() + timedelta(days=2)
    if due_date.isoweekday() == 7:  # the API rejects homework due on Sunday
        due_date += timedelta(days=1)
    due = due_date.isoformat()
    hw_res = await client.post(
        "/api/v1/homework",
        headers=auth_headers,
        json={
            "subject_id": subj_id,
            "lesson_id": whole_id,
            "title": "Упражнение 42",
            "due_date": due,
        },
    )
    assert hw_res.status_code == 201
    orig_hw_id = hw_res.json()["id"]

    clone_whole = await client.post(
        f"/api/v1/schedule/{whole_id}/clone",
        headers=auth_headers,
    )
    assert clone_whole.status_code == 201
    cloned_lesson_id = clone_whole.json()["id"]
    assert str(clone_whole.json()["subgroup"]) == "2"

    # Verify original whole-class lesson was converted to subgroup 1
    get_orig = await client.get("/api/v1/schedule", headers=auth_headers)
    thursday_lessons = [l for l in get_orig.json() if l["day_of_week"] == 4 and l["lesson_number"] == 2]
    assert len(thursday_lessons) == 2
    subgroups = {str(l["subgroup"]) for l in thursday_lessons}
    assert subgroups == {"1", "2"}

    # Verify homework was duplicated for the cloned lesson
    all_hw = (await client.get("/api/v1/homework", headers=auth_headers)).json()
    hw_for_slot = [h for h in all_hw if h["title"] == "Упражнение 42"]
    assert len(hw_for_slot) == 2
    hw_subs = {str(h["subgroup"]) for h in hw_for_slot}
    assert hw_subs == {"1", "2"}
    hw_lesson_ids = {h["lesson_id"] for h in hw_for_slot}
    assert hw_lesson_ids == {whole_id, cloned_lesson_id}
