from datetime import date
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.config import get_settings
from locus.models.homework import Homework
from locus.models.lesson import Lesson
from locus.models.subject import Subject
from locus.models.user import User
from locus.schedule_validation import LessonConflictError, validate_lesson_conflict
from locus.security import create_access_token, get_password_fingerprint, hash_password


@pytest.mark.asyncio
async def test_subgroup_lesson_conflict_rules(
    db_session: AsyncSession,
    test_subject: Subject,
):
    # Lesson for subgroup 1
    l1 = Lesson(
        subject_id=test_subject.id,
        day_of_week=1,
        lesson_number=1,
        start_time="08:00",
        end_time="08:45",
        week_type="ALL",
        subgroup=1,
    )
    db_session.add(l1)
    await db_session.commit()

    # Lesson for subgroup 2 at the same slot - ALLOWED
    await validate_lesson_conflict(
        db=db_session,
        day_of_week=1,
        lesson_number=1,
        start_time="08:00",
        end_time="08:45",
        week_type="ALL",
        subgroup=2,
    )

    # Adding second lesson for subgroup 2
    l2 = Lesson(
        subject_id=test_subject.id,
        day_of_week=1,
        lesson_number=1,
        start_time="08:00",
        end_time="08:45",
        week_type="ALL",
        subgroup=2,
    )
    db_session.add(l2)
    await db_session.commit()

    # Another lesson for subgroup 1 with same number - CONFLICT
    with pytest.raises(LessonConflictError, match="уже существует"):
        await validate_lesson_conflict(
            db=db_session,
            day_of_week=1,
            lesson_number=1,
            start_time="08:00",
            end_time="08:45",
            week_type="ALL",
            subgroup=1,
        )

    # Lesson for whole class (subgroup=None) with same number - CONFLICT
    with pytest.raises(LessonConflictError, match="уже существует"):
        await validate_lesson_conflict(
            db=db_session,
            day_of_week=1,
            lesson_number=1,
            start_time="08:00",
            end_time="08:45",
            week_type="ALL",
            subgroup=None,
        )

    # Lesson for subgroup 2 with overlapping time - CONFLICT
    with pytest.raises(LessonConflictError, match="пересекается"):
        await validate_lesson_conflict(
            db=db_session,
            day_of_week=1,
            lesson_number=2,
            start_time="08:30",
            end_time="09:15",
            week_type="ALL",
            subgroup=2,
        )


@pytest.mark.asyncio
async def test_admin_creates_and_updates_user_subgroup(
    client: AsyncClient,
    auth_cookies: dict,
    db_session: AsyncSession,
):
    # 1. Create user with subgroup 1
    resp = await client.post(
        "/admin/users",
        data={
            "username": "alice",
            "password": "password123",
            "subgroup": "1",
        },
        cookies=auth_cookies,
        follow_redirects=True,
    )
    assert resp.status_code == 200

    alice = (
        await db_session.execute(select(User).where(User.username == "alice"))
    ).scalar_one()
    assert alice.subgroup == 1

    # 2. Update user to subgroup 2
    update_resp = await client.post(
        f"/admin/users/{alice.id}/subgroup",
        data={"subgroup": "2"},
        cookies=auth_cookies,
        follow_redirects=True,
    )
    assert update_resp.status_code == 200
    await db_session.refresh(alice)
    assert alice.subgroup == 2

    # 3. Clear user subgroup
    clear_resp = await client.post(
        f"/admin/users/{alice.id}/subgroup",
        data={"subgroup": ""},
        cookies=auth_cookies,
        follow_redirects=True,
    )
    assert clear_resp.status_code == 200
    await db_session.refresh(alice)
    assert alice.subgroup is None


@pytest.mark.asyncio
async def test_homework_isolation_by_subgroup(
    client: AsyncClient,
    db_session: AsyncSession,
    test_subject: Subject,
    auth_cookies: dict,
):
    settings = get_settings()

    # Create students
    u1 = User(
        username="group1_student",
        hashed_password=hash_password("password123"),
        is_active=True,
        is_admin=False,
        subgroup=1,
    )
    u2 = User(
        username="group2_student",
        hashed_password=hash_password("password123"),
        is_active=True,
        is_admin=False,
        subgroup=2,
    )
    db_session.add_all([u1, u2])
    await db_session.commit()
    await db_session.refresh(u1)
    await db_session.refresh(u2)

    t1 = create_access_token({"sub": str(u1.id), "pwd": get_password_fingerprint(u1.hashed_password)})
    t2 = create_access_token({"sub": str(u2.id), "pwd": get_password_fingerprint(u2.hashed_password)})

    # Homeworks
    hw_general = Homework(
        subject_id=test_subject.id,
        title="Общее ДЗ",
        due_date=date(2026, 11, 2),
        subgroup=None,
    )
    hw_g1 = Homework(
        subject_id=test_subject.id,
        title="ДЗ только для 1 группы",
        due_date=date(2026, 11, 2),
        subgroup=1,
    )
    hw_g2 = Homework(
        subject_id=test_subject.id,
        title="ДЗ только для 2 группы",
        due_date=date(2026, 11, 2),
        subgroup=2,
    )
    db_session.add_all([hw_general, hw_g1, hw_g2])
    await db_session.commit()

    # Query as student 1 (web)
    r1 = await client.get("/homework", cookies={settings.COOKIE_NAME: t1})
    assert r1.status_code == 200
    assert "Общее ДЗ" in r1.text
    assert "ДЗ только для 1 группы" in r1.text
    assert "ДЗ только для 2 группы" not in r1.text

    # Query as student 2 (web)
    r2 = await client.get("/homework", cookies={settings.COOKIE_NAME: t2})
    assert r2.status_code == 200
    assert "Общее ДЗ" in r2.text
    assert "ДЗ только для 1 группы" not in r2.text
    assert "ДЗ только для 2 группы" in r2.text

    # Query as student 1 (API)
    api_r1 = await client.get("/api/v1/homework", headers={"Authorization": f"Bearer {t1}"})
    assert api_r1.status_code == 200
    titles1 = [h["title"] for h in api_r1.json()]
    assert "Общее ДЗ" in titles1
    assert "ДЗ только для 1 группы" in titles1
    assert "ДЗ только для 2 группы" not in titles1

    # Query as admin (API with subgroup filter)
    admin_r = await client.get(
        "/api/v1/homework?subgroup=2",
        cookies=auth_cookies,
    )
    assert admin_r.status_code == 200
    admin_titles = [h["title"] for h in admin_r.json()]
    assert "Общее ДЗ" in admin_titles
    assert "ДЗ только для 2 группы" in admin_titles
    assert "ДЗ только для 1 группы" not in admin_titles


@pytest.mark.asyncio
async def test_dashboard_subgroup_parallel_lesson_display(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_cookies: dict,
):
    settings = get_settings()

    s1 = Subject(name="Английский", teacher_name="Смит Д.", room="101")
    s2 = Subject(name="Информатика", teacher_name="Байтов И.", room="202")
    db_session.add_all([s1, s2])
    await db_session.commit()
    await db_session.refresh(s1)
    await db_session.refresh(s2)

    # Monday lesson 1 for subgroup 1 and subgroup 2
    l1 = Lesson(
        subject_id=s1.id,
        day_of_week=1,
        lesson_number=1,
        start_time="08:00",
        end_time="08:45",
        week_type="ALL",
        subgroup=1,
    )
    l2 = Lesson(
        subject_id=s2.id,
        day_of_week=1,
        lesson_number=1,
        start_time="08:00",
        end_time="08:45",
        week_type="ALL",
        subgroup=2,
    )
    db_session.add_all([l1, l2])

    student1 = User(
        username="john",
        hashed_password=hash_password("pass123"),
        is_active=True,
        is_admin=False,
        subgroup=1,
    )
    student2 = User(
        username="jane",
        hashed_password=hash_password("pass123"),
        is_active=True,
        is_admin=False,
        subgroup=2,
    )
    db_session.add_all([student1, student2])
    await db_session.commit()
    await db_session.refresh(student1)
    await db_session.refresh(student2)

    t1 = create_access_token({"sub": str(student1.id), "pwd": get_password_fingerprint(student1.hashed_password)})
    t2 = create_access_token({"sub": str(student2.id), "pwd": get_password_fingerprint(student2.hashed_password)})

    target_monday = "2026-10-26"  # A Monday

    # Student 1 view
    r1 = await client.get(f"/?date={target_monday}", cookies={settings.COOKIE_NAME: t1})
    assert r1.status_code == 200
    assert f'id="lesson-card-{l1.id}"' in r1.text
    assert f'id="lesson-card-{l2.id}"' not in r1.text
    # Parallel lesson is NOT displayed on dashboard card
    assert "Параллельно:" not in r1.text
    assert "group/parallel" not in r1.text

    # Student 2 view
    r2 = await client.get(f"/?date={target_monday}", cookies={settings.COOKIE_NAME: t2})
    assert r2.status_code == 200
    assert f'id="lesson-card-{l2.id}"' in r2.text
    assert f'id="lesson-card-{l1.id}"' not in r2.text
    assert "Параллельно:" not in r2.text
    assert "group/parallel" not in r2.text

    # Test save_lesson_homework OOB response does not have parallel lesson
    save_resp = await client.post(
        f"/dashboard/lesson/{l1.id}/homework?date={target_monday}",
        data={"title": "Новое ДЗ по английскому", "is_done": False},
        cookies={settings.COOKIE_NAME: t1},
    )
    assert save_resp.status_code == 200
    assert "Параллельно:" not in save_resp.text
    assert "group/parallel" not in save_resp.text


@pytest.mark.asyncio
async def test_homework_security_cross_subgroup_prohibited(
    client: AsyncClient,
    db_session: AsyncSession,
    test_subject: Subject,
):
    settings = get_settings()

    u1 = User(
        username="s1",
        hashed_password=hash_password("pass123"),
        is_active=True,
        is_admin=False,
        subgroup=1,
    )
    u2 = User(
        username="s2",
        hashed_password=hash_password("pass123"),
        is_active=True,
        is_admin=False,
        subgroup=2,
    )
    db_session.add_all([u1, u2])
    await db_session.commit()
    await db_session.refresh(u1)
    await db_session.refresh(u2)

    t1 = create_access_token({"sub": str(u1.id), "pwd": get_password_fingerprint(u1.hashed_password)})
    t2 = create_access_token({"sub": str(u2.id), "pwd": get_password_fingerprint(u2.hashed_password)})

    hw2 = Homework(
        subject_id=test_subject.id,
        title="Задание группы 2",
        due_date=date(2026, 11, 2),
        subgroup=2,
    )
    db_session.add(hw2)
    await db_session.commit()
    await db_session.refresh(hw2)

    # 1. Student 1 cannot view Homework 2 via direct API (404)
    r_get = await client.get(f"/api/v1/homework/{hw2.id}", headers={"Authorization": f"Bearer {t1}"})
    assert r_get.status_code == 404

    # 2. Student 1 cannot update Homework 2 (403)
    r_put = await client.put(
        f"/api/v1/homework/{hw2.id}",
        json={"title": "Взлом"},
        headers={"Authorization": f"Bearer {t1}"},
    )
    assert r_put.status_code == 403

    # 3. Student 1 cannot delete Homework 2 via API (403) or Web (403)
    r_del = await client.delete(
        f"/api/v1/homework/{hw2.id}",
        headers={"Authorization": f"Bearer {t1}"},
    )
    assert r_del.status_code == 403

    r_web_del = await client.delete(
        f"/homework/{hw2.id}",
        cookies={settings.COOKIE_NAME: t1},
    )
    assert r_web_del.status_code == 403

    # 4. Student 1 cannot create homework for subgroup 2 (403)
    r_create_api = await client.post(
        "/api/v1/homework",
        json={
            "subject_id": test_subject.id,
            "title": "Фейк",
            "due_date": "2026-11-02",
            "subgroup": 2,
        },
        headers={"Authorization": f"Bearer {t1}"},
    )
    assert r_create_api.status_code == 403

    r_create_web = await client.post(
        "/homework",
        data={
            "subject_id": str(test_subject.id),
            "title": "Фейк веб",
            "due_date": "2026-11-02",
            "subgroup": "2",
        },
        cookies={settings.COOKIE_NAME: t1},
    )
    assert r_create_web.status_code == 403


@pytest.mark.asyncio
async def test_invalid_subgroup_validation(
    client: AsyncClient,
    auth_cookies: dict,
    test_subject: Subject,
):
    # Invalid subgroup in admin user creation
    r1 = await client.post(
        "/admin/users",
        data={"username": "bob_invalid", "password": "password123", "subgroup": "99"},
        cookies=auth_cookies,
    )
    assert r1.status_code == 400

    # Invalid subgroup in schedule lesson creation
    r2 = await client.post(
        "/schedule",
        data={
            "subject_id": test_subject.id,
            "day_of_week": 1,
            "lesson_number": 8,
            "start_time": "14:40",
            "end_time": "15:25",
            "subgroup": 99,
        },
        cookies=auth_cookies,
    )
    assert r2.status_code == 400

    # Invalid subgroup in admin user subgroup update (verifying no NameError)
    # First create a valid user
    r_create = await client.post(
        "/admin/users",
        data={"username": "test_user_sub", "password": "password123", "subgroup": "1"},
        cookies=auth_cookies,
        follow_redirects=True,
    )
    assert r_create.status_code == 200
    user_row = (await client.get("/admin/users", cookies=auth_cookies)).text
    assert "test_user_sub" in user_row

    # Update with invalid subgroup
    r3 = await client.post(
        "/admin/users/1/subgroup",
        data={"subgroup": "99"},
        cookies=auth_cookies,
    )
    assert r3.status_code == 400
    assert "Номер подгруппы должен быть 1 или 2" in r3.text


@pytest.mark.asyncio
async def test_common_subject_cannot_have_subgroup_homework(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_cookies: dict,
    auth_headers: dict,
):
    # Common subject (e.g. Algebra) without any subgroup lessons
    common_sub = Subject(name="Алгебра", room="201")
    db_session.add(common_sub)
    await db_session.commit()
    await db_session.refresh(common_sub)

    # 1. Via Web: Attempt to create subgroup HW for common subject -> coerced to None
    r_web = await client.post(
        "/homework",
        data={
            "subject_id": str(common_sub.id),
            "title": "№ 123",
            "due_date": "2026-11-03",
            "subgroup": "1",
        },
        cookies=auth_cookies,
        follow_redirects=True,
    )
    assert r_web.status_code == 200

    hw_row = (
        await db_session.execute(select(Homework).where(Homework.subject_id == common_sub.id))
    ).scalar_one()
    assert hw_row.subgroup is None  # Locked to class-wide

    # 2. Via API: Attempt to create subgroup HW for common subject -> coerced to None
    r_api = await client.post(
        "/api/v1/homework",
        json={
            "subject_id": common_sub.id,
            "title": "№ 124",
            "due_date": "2026-11-04",
            "subgroup": 2,
        },
        headers=auth_headers,
    )
    assert r_api.status_code == 201
    assert r_api.json()["subgroup"] is None


@pytest.mark.asyncio
async def test_unassigned_hw_assigned_to_subgroup_lesson_updates_subgroup(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_cookies: dict,
):
    sub = Subject(name="Информатика")
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)

    lesson_sub2 = Lesson(
        subject_id=sub.id,
        day_of_week=3,
        lesson_number=2,
        start_time="08:55",
        end_time="09:40",
        week_type="ALL",
        subgroup=2,
    )
    db_session.add(lesson_sub2)

    # Create unassigned homework with subgroup=None
    hw = Homework(
        subject_id=sub.id,
        title="Практическая работа",
        due_date=date(2026, 10, 28),
        subgroup=None,
    )
    db_session.add(hw)
    await db_session.commit()
    await db_session.refresh(hw)
    assert hw.lesson_id is None
    assert hw.subgroup is None

    # Save via lesson modal of subgroup 2
    r = await client.post(
        f"/dashboard/lesson/{lesson_sub2.id}/homework?date=2026-10-28",
        data={
            "hw_id": str(hw.id),
            "title": "Практическая работа обновленная",
            "is_done": False,
        },
        cookies=auth_cookies,
    )
    assert r.status_code == 200

    await db_session.refresh(hw)
    assert hw.lesson_id == lesson_sub2.id
    assert hw.subgroup == 2  # Automatically synced with lesson's subgroup!


@pytest.mark.asyncio
async def test_different_teachers_per_subgroup_lesson(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_cookies: dict,
    auth_headers: dict,
):
    # 1. Create Subject with teachers and rooms for both subgroups via Web form
    r_subj = await client.post(
        "/subjects",
        data={
            "name": "Иностранный язык",
            "teacher_name": "Иванова А.А. (Подгр. 1)",
            "teacher_phone": "+7 (999) 111-11-11",
            "room": "101",
            "teacher2_name": "Петрова Б.Б. (Подгр. 2)",
            "teacher2_phone": "+7 (999) 222-22-22",
            "room2": "102",
        },
        cookies=auth_cookies,
        follow_redirects=True,
    )
    assert r_subj.status_code == 200

    subj_stmt = select(Subject).where(Subject.name == "Иностранный язык")
    res_subj = await db_session.execute(subj_stmt)
    subj = res_subj.scalar_one()

    assert subj.teacher_name == "Иванова А.А. (Подгр. 1)"
    assert subj.teacher2_name == "Петрова Б.Б. (Подгр. 2)"
    assert subj.room == "101"
    assert subj.room2 == "102"
    assert subj.get_teacher_name(1) == "Иванова А.А. (Подгр. 1)"
    assert subj.get_teacher_name(2) == "Петрова Б.Б. (Подгр. 2)"
    assert subj.get_room(1) == "101"
    assert subj.get_room(2) == "102"

    # 2. Check /subjects page renders both subgroup teachers
    subjects_page = await client.get("/subjects", cookies=auth_cookies)
    assert subjects_page.status_code == 200
    assert "Иванова А.А. (Подгр. 1)" in subjects_page.text
    assert "Петрова Б.Б. (Подгр. 2)" in subjects_page.text
    assert "2 подгруппа" in subjects_page.text

    # 3. Create subgroup 1 lesson via Web form
    r_web1 = await client.post(
        "/schedule",
        data={
            "subject_id": str(subj.id),
            "day_of_week": "2",
            "lesson_number": "1",
            "start_time": "08:00",
            "end_time": "08:45",
            "subgroup": "1",
            "room": "",
        },
        cookies=auth_cookies,
        follow_redirects=True,
    )
    assert r_web1.status_code == 200

    # 4. Create subgroup 2 lesson via API
    r_api2 = await client.post(
        "/api/v1/schedule",
        json={
            "subject_id": subj.id,
            "day_of_week": 2,
            "lesson_number": 1,
            "start_time": "08:00",
            "end_time": "08:45",
            "subgroup": 2,
        },
        headers=auth_headers,
    )
    assert r_api2.status_code == 201

    # 5. Create class-wide lesson 2
    r_web3 = await client.post(
        "/schedule",
        data={
            "subject_id": str(subj.id),
            "day_of_week": "2",
            "lesson_number": "2",
            "start_time": "08:55",
            "end_time": "09:40",
            "subgroup": "",
            "room": "Актовый зал",
        },
        cookies=auth_cookies,
        follow_redirects=True,
    )
    assert r_web3.status_code == 200

    # Verify lessons in DB
    lessons_stmt = (
        select(Lesson)
        .where(Lesson.subject_id == subj.id, Lesson.day_of_week == 2)
        .order_by(Lesson.lesson_number, Lesson.subgroup)
    )
    res = await db_session.execute(lessons_stmt)
    lessons = res.scalars().all()
    assert len(lessons) == 3

    l1 = next(l for l in lessons if l.lesson_number == 1 and l.subgroup == 1)
    l2 = next(l for l in lessons if l.lesson_number == 1 and l.subgroup == 2)
    l3 = next(l for l in lessons if l.lesson_number == 2)

    assert l1.effective_teacher_name == "Иванова А.А. (Подгр. 1)"
    assert l2.effective_teacher_name == "Петрова Б.Б. (Подгр. 2)"
    assert l3.effective_teacher_name == "Иванова А.А. (Подгр. 1)"

    assert l1.effective_room == "101"
    assert l2.effective_room == "102"
    assert l3.effective_room == "Актовый зал"  # Specific lesson room override

    # Check schedule page displays both teachers
    sched_resp = await client.get("/schedule", cookies=auth_cookies)
    assert sched_resp.status_code == 200
    assert "Иванова А.А. (Подгр. 1)" in sched_resp.text
    assert "Петрова Б.Б. (Подгр. 2)" in sched_resp.text

    # Check lesson detail modals
    # Modal for lesson 1 (subgroup 1)
    m1 = await client.get(
        f"/dashboard/lesson/{l1.id}/modal?date=2026-10-27",
        cookies=auth_cookies,
    )
    assert m1.status_code == 200
    assert "Иванова А.А. (Подгр. 1)" in m1.text
    assert "+7 (999) 111-11-11" in m1.text

    # Modal for lesson 2 (subgroup 2)
    m2 = await client.get(
        f"/dashboard/lesson/{l2.id}/modal?date=2026-10-27",
        cookies=auth_cookies,
    )
    assert m2.status_code == 200
    assert "Петрова Б.Б. (Подгр. 2)" in m2.text
    assert "+7 (999) 222-22-22" in m2.text

    # Modal for lesson 3 (class-wide / fallback to default teacher)
    m3 = await client.get(
        f"/dashboard/lesson/{l3.id}/modal?date=2026-10-27",
        cookies=auth_cookies,
    )
    assert m3.status_code == 200
    assert "Иванова А.А. (Подгр. 1)" in m3.text
    assert "Каб. Актовый зал" in m3.text

    # Verify no room or contact leaks
    subj_leak_check = Subject(
        name="Физика",
        teacher_name="Учитель 1",
        teacher_phone="+79991111111",
        room="101",
        teacher2_name="Учитель 2",
        teacher2_phone=None,
        room2=None,
    )
    assert subj_leak_check.get_room(1) == "101"
    assert subj_leak_check.get_room(2) is None
    assert subj_leak_check.get_teacher_phone(1) == "+79991111111"
    assert subj_leak_check.get_teacher_phone(2) is None
    assert subj_leak_check.get_whatsapp_url(2) is None

    # When subgroup 2 teacher is completely unset, returns None (no leak from subgroup 1)
    subj_no_teacher2 = Subject(
        name="Химия",
        teacher_name="Учитель 1",
        teacher_phone="+79991111111",
        room="101",
        teacher2_name=None,
        teacher2_phone=None,
        room2=None,
    )
    assert subj_no_teacher2.get_teacher_name(2) is None
    assert subj_no_teacher2.get_teacher_phone(2) is None
    assert subj_no_teacher2.get_whatsapp_url(2) is None
    assert subj_no_teacher2.get_room(2) is None

    # Student creates homework for whole class with subgroup=""
    r_hw_all = await client.post(
        "/homework",
        data={
            "subject_id": str(subj.id),
            "due_date": "2026-10-29",
            "title": "Общее задание для всех",
            "subgroup": "",
        },
        cookies=auth_cookies,
        follow_redirects=True,
    )
    assert r_hw_all.status_code == 200

    hw_all_stmt = select(Homework).where(Homework.title == "Общее задание для всех")
    hw_all = (await db_session.execute(hw_all_stmt)).scalar_one()
    assert hw_all.subgroup is None

    # Test update_homework validation in API
    r_update_conflict = await client.put(
        f"/api/v1/homework/{hw_all.id}",
        json={"lesson_id": l1.id, "subgroup": 2},
        headers=auth_headers,
    )
    assert r_update_conflict.status_code == 400


@pytest.mark.asyncio
async def test_next_lesson_suggestion_includes_subgroup(
    db_session: AsyncSession,
):
    from datetime import datetime
    from locus.lesson_suggestion import get_next_lesson_suggestion

    subj = Subject(name="Информатика", teacher_name="Учитель 1", teacher2_name="Учитель 2")
    db_session.add(subj)
    await db_session.commit()

    # Source lesson: Monday (day 1) 08:30-09:15 for subgroup 2
    l_source = Lesson(
        subject_id=subj.id,
        day_of_week=1,
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
        week_type="ALL",
        subgroup=2,
    )
    # Next lesson: Wednesday (day 3) 10:00-10:45 for subgroup 2
    l_target = Lesson(
        subject_id=subj.id,
        day_of_week=3,
        lesson_number=2,
        start_time="10:00",
        end_time="10:45",
        week_type="ALL",
        subgroup=2,
    )
    db_session.add_all([l_source, l_target])
    await db_session.commit()

    # Now is Monday 08:45 (during source lesson)
    now = datetime(2026, 10, 26, 8, 45)  # Monday
    suggestion = get_next_lesson_suggestion(
        lessons=[l_source, l_target],
        now=now,
        subgroup=2,
    )
    assert suggestion is not None
    assert suggestion["subgroup"] == 2
    assert suggestion["target_lesson_id"] == l_target.id


@pytest.mark.asyncio
async def test_subject_card_subgroup_badges_and_empty_divider(
    client: AsyncClient,
    db_session: AsyncSession,
):
    # Create empty subject "Мяу"
    subj_empty = Subject(name="Мяу")
    # Create subject with 2 subgroups
    subj_sub = Subject(
        name="Английский язык",
        teacher_name="Иванова",
        room="101",
        teacher2_name="Петрова",
        room2="102",
    )
    # Create user in subgroup 1 and user in subgroup 2
    u1 = User(
        username="student_sub1",
        hashed_password=hash_password("pass123"),
        subgroup=1,
        is_active=True,
    )
    u2 = User(
        username="student_sub2",
        hashed_password=hash_password("pass123"),
        subgroup=2,
        is_active=True,
    )
    db_session.add_all([subj_empty, subj_sub, u1, u2])
    await db_session.commit()
    await db_session.refresh(u1)
    await db_session.refresh(u2)

    settings = get_settings()
    t1 = create_access_token({"sub": str(u1.id), "pwd": get_password_fingerprint(u1.hashed_password)})
    t2 = create_access_token({"sub": str(u2.id), "pwd": get_password_fingerprint(u2.hashed_password)})

    # Fetch page as user in subgroup 1
    res1 = await client.get("/subjects", cookies={settings.COOKIE_NAME: t1})
    assert res1.status_code == 200
    html1 = res1.text

    # Verify no "1 подгруппа / общий" text anywhere
    assert "1 подгруппа / общий" not in html1
    # Verify "1 подгруппа" and "2 подгруппа" exist
    assert "1 подгруппа" in html1
    assert "2 подгруппа" in html1

    # In user 1's view, Subgroup 1 badge has emerald border, Subgroup 2 badge has transparent border
    assert 'border-emerald-500/25 text-[10px] font-semibold">1 подгруппа</span>' in html1
    assert 'border-transparent text-[10px] font-semibold">2 подгруппа</span>' in html1

    # Fetch page as user in subgroup 2
    res2 = await client.get("/subjects", cookies={settings.COOKIE_NAME: t2})
    assert res2.status_code == 200
    html2 = res2.text

    # In user 2's view, Subgroup 2 badge has emerald border, Subgroup 1 badge has transparent border
    assert 'border-transparent text-[10px] font-semibold">1 подгруппа</span>' in html2
    assert 'border-emerald-500/25 text-[10px] font-semibold">2 подгруппа</span>' in html2

    # Verify empty subject "Мяу" has no divider border-t border-zinc-800/70 inside its card
    # Find card content around "Мяу"
    idx_myau = html1.find("Мяу")
    assert idx_myau != -1
    # Next card or end of grid
    next_card = html1.find("bg-[#18181b] border border-zinc-800/80 rounded-2xl", idx_myau)
    myau_card = html1[idx_myau:next_card if next_card != -1 else idx_myau + 500]
    assert "border-t border-zinc-800/70" not in myau_card

    # Create subject with only subgroup 2 info
    subj_only_sub2 = Subject(name="Информатика спец", teacher2_name="Сидоров")
    db_session.add(subj_only_sub2)
    await db_session.commit()

    res3 = await client.get("/subjects", cookies={settings.COOKIE_NAME: t1})
    html3 = res3.text
    idx_info = html3.find("Информатика спец")
    assert idx_info != -1
    info_card = html3[idx_info:idx_info + 1500]
    # Subgroup 1 should be completely hidden, subgroup 2 shown
    assert "2 подгруппа" in info_card
    assert "Сидоров" in info_card
    assert "1 подгруппа" not in info_card


@pytest.mark.asyncio
async def test_subgroup_security_bypass_and_lesson_modal_protection(
    client: AsyncClient,
    db_session: AsyncSession,
    test_subject: Subject,
):
    settings = get_settings()

    # Create users in subgroup 1 and subgroup 2
    u1 = User(
        username="sec_user_sub1",
        hashed_password=hash_password("pass123"),
        subgroup=1,
        is_active=True,
    )
    u2 = User(
        username="sec_user_sub2",
        hashed_password=hash_password("pass123"),
        subgroup=2,
        is_active=True,
    )
    db_session.add_all([u1, u2])
    await db_session.commit()
    await db_session.refresh(u1)
    await db_session.refresh(u2)

    t1 = create_access_token({"sub": str(u1.id), "pwd": get_password_fingerprint(u1.hashed_password)})

    # Lesson for subgroup 2
    l2 = Lesson(
        subject_id=test_subject.id,
        day_of_week=2,
        lesson_number=3,
        start_time="10:00",
        end_time="10:45",
        week_type="ALL",
        subgroup=2,
    )
    db_session.add(l2)
    await db_session.commit()
    await db_session.refresh(l2)

    # 1. User 1 cannot open modal for subgroup 2's lesson (403 Forbidden)
    res_modal = await client.get(
        f"/dashboard/lesson/{l2.id}/modal?date=2026-10-27",
        cookies={settings.COOKIE_NAME: t1},
    )
    assert res_modal.status_code == 403

    # 2. User 1 cannot create homework for subgroup 2 via lesson_id without specifying subgroup (API)
    res_api_create = await client.post(
        "/api/v1/homework",
        json={
            "subject_id": test_subject.id,
            "lesson_id": l2.id,
            "title": "Хак через lesson_id",
            "due_date": "2026-10-27",
        },
        headers={"Authorization": f"Bearer {t1}"},
    )
    assert res_api_create.status_code == 403

    # 3. User 1 cannot create homework for subgroup 2 via lesson_id without specifying subgroup (Web)
    res_web_create = await client.post(
        "/homework",
        data={
            "subject_id": str(test_subject.id),
            "lesson_id": str(l2.id),
            "title": "Хак веб",
            "due_date": "2026-10-27",
        },
        cookies={settings.COOKIE_NAME: t1},
    )
    assert res_web_create.status_code == 403

    # 4. User 1 cannot update unassigned homework to target lesson of subgroup 2 (API)
    hw_unassigned = Homework(
        subject_id=test_subject.id,
        title="Общее незакрепленное",
        due_date=date(2026, 10, 27),
    )
    db_session.add(hw_unassigned)
    await db_session.commit()
    await db_session.refresh(hw_unassigned)

    res_api_update = await client.put(
        f"/api/v1/homework/{hw_unassigned.id}",
        json={"lesson_id": l2.id},
        headers={"Authorization": f"Bearer {t1}"},
    )
    assert res_api_update.status_code == 403


@pytest.mark.asyncio
async def test_unassigned_general_homework_in_both_parallel_cards(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_cookies: dict,
):
    # Subject with 2 subgroups
    subj = Subject(name="Физика", teacher_name="Учитель 1", teacher2_name="Учитель 2")
    db_session.add(subj)
    await db_session.commit()

    # Parallel lessons: Tuesday (day 2) lesson 1 for subgroup 1 and subgroup 2
    l1 = Lesson(
        subject_id=subj.id,
        day_of_week=2,
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
        week_type="ALL",
        subgroup=1,
    )
    l2 = Lesson(
        subject_id=subj.id,
        day_of_week=2,
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
        week_type="ALL",
        subgroup=2,
    )
    # General unassigned homework for the whole class
    hw_gen = Homework(
        subject_id=subj.id,
        title="Общая лабораторная",
        due_date=date(2026, 10, 27),  # Tuesday
        subgroup=None,
    )
    db_session.add_all([l1, l2, hw_gen])
    await db_session.commit()

    # Admin visits dashboard for 2026-10-27 with subgroup filter "Все" (no subgroup param)
    res = await client.get("/?date=2026-10-27", cookies=auth_cookies)
    assert res.status_code == 200
    html = res.text

    # The title "Общая лабораторная" should appear in both parallel cards (count >= 2)
    assert html.count("Общая лабораторная") >= 2



