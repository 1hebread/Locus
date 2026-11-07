from datetime import date
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.constants import get_current_date
from locus.models.homework import Homework
from locus.models.lesson import Lesson
from locus.models.subject import Subject
from locus.models.user import User
from locus.schedule_validation import LessonConflictError, validate_lesson_conflict
from locus.security import create_access_token, get_password_fingerprint, hash_password
from tests.helpers import next_valid_due_date


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
    auth_headers: dict,
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
        headers=auth_headers,
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
        headers=auth_headers,
        follow_redirects=True,
    )
    assert update_resp.status_code == 200
    await db_session.refresh(alice)
    assert alice.subgroup == 2

    # 3. Clear user subgroup
    clear_resp = await client.post(
        f"/admin/users/{alice.id}/subgroup",
        data={"subgroup": ""},
        headers=auth_headers,
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
    auth_headers: dict,
):
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

    # Homeworks (future-dated: the web page hides past-due homework)
    due_date = next_valid_due_date(1)
    hw_general = Homework(
        subject_id=test_subject.id,
        title="Общее ДЗ",
        due_date=due_date,
        subgroup=None,
    )
    hw_g1 = Homework(
        subject_id=test_subject.id,
        title="ДЗ только для 1 группы",
        due_date=due_date,
        subgroup=1,
    )
    hw_g2 = Homework(
        subject_id=test_subject.id,
        title="ДЗ только для 2 группы",
        due_date=due_date,
        subgroup=2,
    )
    db_session.add_all([hw_general, hw_g1, hw_g2])
    await db_session.commit()

    # Query as student 1 (web)
    r1 = await client.get("/homework", headers={"Authorization": f"Bearer {t1}"})
    assert r1.status_code == 200
    assert "Общее ДЗ" in r1.text
    assert "ДЗ только для 1 группы" in r1.text
    assert "ДЗ только для 2 группы" not in r1.text

    # Query as student 2 (web)
    r2 = await client.get("/homework", headers={"Authorization": f"Bearer {t2}"})
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
        headers=auth_headers,
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
):
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
    r1 = await client.get(f"/?date={target_monday}", headers={"Authorization": f"Bearer {t1}"})
    assert r1.status_code == 200
    assert f'id="lesson-card-{l1.id}"' in r1.text
    assert f'id="lesson-card-{l2.id}"' not in r1.text
    # Parallel lesson is NOT displayed on dashboard card
    assert "Параллельно:" not in r1.text
    assert "group/parallel" not in r1.text

    # Student 2 view
    r2 = await client.get(f"/?date={target_monday}", headers={"Authorization": f"Bearer {t2}"})
    assert r2.status_code == 200
    assert f'id="lesson-card-{l2.id}"' in r2.text
    assert f'id="lesson-card-{l1.id}"' not in r2.text
    assert "Параллельно:" not in r2.text
    assert "group/parallel" not in r2.text

    # Test save_lesson_homework OOB response does not have parallel lesson
    save_resp = await client.post(
        f"/dashboard/lesson/{l1.id}/homework?date={target_monday}",
        data={"title": "Новое ДЗ по английскому", "is_done": False},
        headers={"Authorization": f"Bearer {t1}"},
    )
    assert save_resp.status_code == 200
    assert "Параллельно:" not in save_resp.text
    assert "group/parallel" not in save_resp.text


@pytest.mark.asyncio
async def test_dashboard_admin_defaults_to_own_subgroup(
    client: AsyncClient,
    db_session: AsyncSession,
):
    s1 = Subject(name="Английский", teacher_name="Смит Д.", room="101")
    s2 = Subject(name="Информатика", teacher_name="Байтов И.", room="202")
    db_session.add_all([s1, s2])
    await db_session.commit()
    await db_session.refresh(s1)
    await db_session.refresh(s2)

    l1 = Lesson(
        subject_id=s1.id, day_of_week=1, lesson_number=1,
        start_time="08:00", end_time="08:45", week_type="ALL", subgroup=1,
    )
    l2 = Lesson(
        subject_id=s2.id, day_of_week=1, lesson_number=1,
        start_time="08:00", end_time="08:45", week_type="ALL", subgroup=2,
    )
    db_session.add_all([l1, l2])

    admin = User(
        username="admin_sub2",
        hashed_password=hash_password("pass123"),
        is_active=True,
        is_admin=True,
        subgroup=2,
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)

    token = create_access_token({
        "sub": str(admin.id),
        "pwd": get_password_fingerprint(admin.hashed_password),
    })
    headers = {"Authorization": f"Bearer {token}"}
    target_monday = "2026-10-26"

    # No explicit filter -> admin's own (2nd) subgroup
    r_default = await client.get(f"/?date={target_monday}", headers=headers)
    assert f'id="lesson-card-{l2.id}"' in r_default.text
    assert f'id="lesson-card-{l1.id}"' not in r_default.text

    # Explicit "all" still shows every subgroup
    r_all = await client.get(f"/?date={target_monday}&subgroup=all", headers=headers)
    assert f'id="lesson-card-{l1.id}"' in r_all.text
    assert f'id="lesson-card-{l2.id}"' in r_all.text


@pytest.mark.asyncio
async def test_homework_security_cross_subgroup_prohibited(
    client: AsyncClient,
    db_session: AsyncSession,
    test_subject: Subject,
):
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
        headers={"Authorization": f"Bearer {t1}"},
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
        headers={"Authorization": f"Bearer {t1}"},
    )
    assert r_create_web.status_code == 403


@pytest.mark.asyncio
async def test_invalid_subgroup_validation(
    client: AsyncClient,
    auth_headers: dict,
    test_subject: Subject,
):
    # Invalid subgroup in admin user creation
    r1 = await client.post(
        "/admin/users",
        data={"username": "bob_invalid", "password": "password123", "subgroup": "99"},
        headers=auth_headers,
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
        headers=auth_headers,
    )
    assert r2.status_code == 400

    # Invalid subgroup in admin user subgroup update (verifying no NameError)
    # First create a valid user
    r_create = await client.post(
        "/admin/users",
        data={"username": "test_user_sub", "password": "password123", "subgroup": "1"},
        headers=auth_headers,
        follow_redirects=True,
    )
    assert r_create.status_code == 200
    user_row = (await client.get("/admin/users", headers=auth_headers)).text
    assert "test_user_sub" in user_row

    # Update with invalid subgroup
    r3 = await client.post(
        "/admin/users/1/subgroup",
        data={"subgroup": "99"},
        headers=auth_headers,
    )
    assert r3.status_code == 400
    assert "Номер подгруппы должен быть 1 или 2" in r3.text


@pytest.mark.asyncio
async def test_common_subject_cannot_have_subgroup_homework(
    client: AsyncClient,
    db_session: AsyncSession,
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
        headers=auth_headers,
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
    auth_headers: dict,
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
        headers=auth_headers,
    )
    assert r.status_code == 200

    await db_session.refresh(hw)
    assert hw.lesson_id == lesson_sub2.id
    assert str(hw.subgroup) == "2"  # Automatically synced with lesson's subgroup!


@pytest.mark.asyncio
async def test_different_teachers_per_subgroup_lesson(
    client: AsyncClient,
    db_session: AsyncSession,
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
        headers=auth_headers,
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
    subjects_page = await client.get("/subjects", headers=auth_headers)
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
        headers=auth_headers,
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
        headers=auth_headers,
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

    l1 = next(l for l in lessons if l.lesson_number == 1 and str(l.subgroup) == "1")
    l2 = next(l for l in lessons if l.lesson_number == 1 and str(l.subgroup) == "2")
    l3 = next(l for l in lessons if l.lesson_number == 2)

    assert l1.effective_teacher_name == "Иванова А.А. (Подгр. 1)"
    assert l2.effective_teacher_name == "Петрова Б.Б. (Подгр. 2)"
    assert l3.effective_teacher_name == "Иванова А.А. (Подгр. 1)"

    assert l1.effective_room == "101"
    assert l2.effective_room == "102"
    assert l3.effective_room == "Актовый зал"  # Specific lesson room override

    # Check schedule page displays both teachers
    sched_resp = await client.get("/schedule", headers=auth_headers)
    assert sched_resp.status_code == 200
    assert "Иванова А.А. (Подгр. 1)" in sched_resp.text
    assert "Петрова Б.Б. (Подгр. 2)" in sched_resp.text

    # Check lesson detail modals
    # Modal for lesson 1 (subgroup 1)
    m1 = await client.get(
        f"/dashboard/lesson/{l1.id}/modal?date=2026-10-27",
        headers=auth_headers,
    )
    assert m1.status_code == 200
    assert "Иванова А.А. (Подгр. 1)" in m1.text
    assert "+7 (999) 111-11-11" in m1.text

    # Modal for lesson 2 (subgroup 2)
    m2 = await client.get(
        f"/dashboard/lesson/{l2.id}/modal?date=2026-10-27",
        headers=auth_headers,
    )
    assert m2.status_code == 200
    assert "Петрова Б.Б. (Подгр. 2)" in m2.text
    assert "+7 (999) 222-22-22" in m2.text

    # Modal for lesson 3 (class-wide / fallback to default teacher)
    m3 = await client.get(
        f"/dashboard/lesson/{l3.id}/modal?date=2026-10-27",
        headers=auth_headers,
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
        headers=auth_headers,
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
async def test_next_lesson_homework_for_both_subgroups(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
):
    subj = Subject(name="Английский 2", teacher_name="Иванова", teacher2_name="Петрова")
    db_session.add(subj)
    await db_session.commit()
    await db_session.refresh(subj)

    current = Lesson(
        subject_id=subj.id,
        day_of_week=1,
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
        week_type="ALL",
        subgroup="1",
    )
    # Both subgroups have the same subject at the same slot next Thursday.
    next_sub1 = Lesson(
        subject_id=subj.id,
        day_of_week=4,
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
        week_type="ALL",
        subgroup="1",
    )
    next_sub2 = Lesson(
        subject_id=subj.id,
        day_of_week=4,
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
        week_type="ALL",
        subgroup="2",
    )
    db_session.add_all([current, next_sub1, next_sub2])
    await db_session.commit()
    await db_session.refresh(current)
    await db_session.refresh(next_sub1)
    await db_session.refresh(next_sub2)

    mon_date = "2026-10-19"
    thu_date = "2026-10-22"

    modal = await client.get(
        f"/dashboard/lesson/{current.id}/modal?date={mon_date}", headers=auth_headers
    )
    assert modal.status_code == 200
    assert "Обеим группам" in modal.text
    assert (
        f'hx-post="/dashboard/lesson/{next_sub1.id}/homework?date={thu_date}'
        f'&forward=true&both_groups=true"'
    ) in modal.text

    save = await client.post(
        f"/dashboard/lesson/{next_sub1.id}/homework?date={thu_date}&forward=true&both_groups=true",
        data={"title": "Общее задание"},
        headers=auth_headers,
    )
    assert save.status_code == 200
    assert "Общее задание" in save.text

    rows = (
        await db_session.execute(
            select(Homework)
            .where(
                Homework.subject_id == subj.id,
                Homework.due_date == date.fromisoformat(thu_date),
            )
            .order_by(Homework.id)
        )
    ).scalars().all()
    assert len(rows) == 2
    by_lesson = {row.lesson_id: row for row in rows}
    assert set(by_lesson) == {next_sub1.id, next_sub2.id}
    assert str(by_lesson[next_sub1.id].subgroup) == "1"
    assert str(by_lesson[next_sub2.id].subgroup) == "2"
    assert all(row.title == "Общее задание" for row in rows)

    # The assignment is visible in both subgroups' lesson modals.
    for lesson in (next_sub1, next_sub2):
        res = await client.get(
            f"/dashboard/lesson/{lesson.id}/modal?date={thu_date}", headers=auth_headers
        )
        assert res.status_code == 200
        assert "Общее задание" in res.text

    # Saving again updates both records instead of duplicating them.
    save_again = await client.post(
        f"/dashboard/lesson/{next_sub1.id}/homework?date={thu_date}&forward=true&both_groups=true",
        data={"title": "Общее задание (уточнено)"},
        headers=auth_headers,
    )
    assert save_again.status_code == 200
    rows = (
        await db_session.execute(
            select(Homework)
            .where(
                Homework.subject_id == subj.id,
                Homework.due_date == date.fromisoformat(thu_date),
            )
            .order_by(Homework.id)
        )
    ).scalars().all()
    assert len(rows) == 2
    assert all(row.title == "Общее задание (уточнено)" for row in rows)

    # Editing one subgroup's copy must not touch the other one.
    edit = await client.post(
        f"/dashboard/lesson/{next_sub1.id}/homework?date={thu_date}",
        data={
            "hw_id": str(by_lesson[next_sub1.id].id),
            "title": "Только для первой",
            "is_done": False,
        },
        headers=auth_headers,
    )
    assert edit.status_code == 200
    await db_session.refresh(by_lesson[next_sub1.id])
    await db_session.refresh(by_lesson[next_sub2.id])
    assert by_lesson[next_sub1.id].title == "Только для первой"
    assert by_lesson[next_sub2.id].title == "Общее задание (уточнено)"

    res2 = await client.get(
        f"/dashboard/lesson/{next_sub2.id}/modal?date={thu_date}", headers=auth_headers
    )
    assert res2.status_code == 200
    assert "Только для первой" not in res2.text
    assert "Общее задание (уточнено)" in res2.text


@pytest.mark.asyncio
async def test_next_lesson_homework_for_both_subgroups_reuses_classwide_record(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
):
    subj = Subject(name="Английский 3")
    db_session.add(subj)
    await db_session.commit()
    await db_session.refresh(subj)

    next_sub1 = Lesson(
        subject_id=subj.id,
        day_of_week=4,
        lesson_number=2,
        start_time="09:25",
        end_time="10:10",
        week_type="ALL",
        subgroup="1",
    )
    next_sub2 = Lesson(
        subject_id=subj.id,
        day_of_week=4,
        lesson_number=2,
        start_time="09:25",
        end_time="10:10",
        week_type="ALL",
        subgroup="2",
    )
    legacy = Homework(
        subject_id=subj.id,
        title="Старое общее",
        due_date=date(2026, 10, 22),
        subgroup=None,
    )
    db_session.add_all([next_sub1, next_sub2, legacy])
    await db_session.commit()
    await db_session.refresh(next_sub1)
    await db_session.refresh(next_sub2)
    await db_session.refresh(legacy)

    save = await client.post(
        f"/dashboard/lesson/{next_sub1.id}/homework?date=2026-10-22&forward=true&both_groups=true",
        data={"title": "Новое общее"},
        headers=auth_headers,
    )
    assert save.status_code == 200

    rows = (
        await db_session.execute(
            select(Homework)
            .where(
                Homework.subject_id == subj.id,
                Homework.due_date == date(2026, 10, 22),
            )
            .order_by(Homework.id)
        )
    ).scalars().all()
    assert len(rows) == 2
    assert {row.lesson_id for row in rows} == {next_sub1.id, next_sub2.id}
    assert all(row.title == "Новое общее" for row in rows)
    # The legacy class-wide record was reused, not orphaned.
    assert legacy.id in {row.id for row in rows}


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

    t1 = create_access_token({"sub": str(u1.id), "pwd": get_password_fingerprint(u1.hashed_password)})
    t2 = create_access_token({"sub": str(u2.id), "pwd": get_password_fingerprint(u2.hashed_password)})

    # Fetch page as user in subgroup 1
    res1 = await client.get("/subjects", headers={"Authorization": f"Bearer {t1}"})
    assert res1.status_code == 200
    html1 = res1.text

    # Verify no "1 подгруппа / общий" text anywhere
    assert "1 подгруппа / общий" not in html1
    # Verify "1 подгруппа" and "2 подгруппа" exist
    assert "1 подгруппа" in html1
    assert "2 подгруппа" in html1

    # In user 1's view, Subgroup 1 badge has emerald border, Subgroup 2 badge has transparent border
    assert 'border-emerald-500/25 text-[10px] font-semibold">1 подгруппа / Мальчики</span>' in html1
    assert 'border-transparent text-[10px] font-semibold">2 подгруппа / Девочки</span>' in html1

    # Fetch page as user in subgroup 2
    res2 = await client.get("/subjects", headers={"Authorization": f"Bearer {t2}"})
    assert res2.status_code == 200
    html2 = res2.text

    # In user 2's view, Subgroup 2 badge has emerald border, Subgroup 1 badge has transparent border
    assert 'border-transparent text-[10px] font-semibold">1 подгруппа / Мальчики</span>' in html2
    assert 'border-emerald-500/25 text-[10px] font-semibold">2 подгруппа / Девочки</span>' in html2

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

    res3 = await client.get("/subjects", headers={"Authorization": f"Bearer {t1}"})
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
        headers={"Authorization": f"Bearer {t1}"},
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
        headers={"Authorization": f"Bearer {t1}"},
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
    auth_headers: dict,
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
    res = await client.get("/?date=2026-10-27", headers=auth_headers)
    assert res.status_code == 200
    html = res.text

    # The title "Общая лабораторная" should appear in both parallel cards (count >= 2)
    assert html.count("Общая лабораторная") >= 2


@pytest.mark.asyncio
async def test_subgroup_lesson_conflict_rules_boys_girls(
    db_session: AsyncSession,
    test_subject: Subject,
):
    # Lesson for boys
    l_boys = Lesson(
        subject_id=test_subject.id,
        day_of_week=1,
        lesson_number=1,
        start_time="08:00",
        end_time="08:45",
        week_type="ALL",
        subgroup="boys",
    )
    db_session.add(l_boys)
    await db_session.commit()

    # Parallel lesson for girls at the same slot - ALLOWED
    await validate_lesson_conflict(
        db=db_session,
        day_of_week=1,
        lesson_number=1,
        start_time="08:00",
        end_time="08:45",
        week_type="ALL",
        subgroup="girls",
    )

    # Adding second lesson for boys at the same slot - CONFLICT
    with pytest.raises(LessonConflictError) as exc:
        await validate_lesson_conflict(
            db=db_session,
            day_of_week=1,
            lesson_number=1,
            start_time="08:00",
            end_time="08:45",
            week_type="ALL",
            subgroup="boys",
        )
    assert "Мальчики" in str(exc.value)

    # Adding academic subgroup '1' overlapping with 'boys' - CONFLICT
    with pytest.raises(LessonConflictError) as exc:
        await validate_lesson_conflict(
            db=db_session,
            day_of_week=1,
            lesson_number=1,
            start_time="08:00",
            end_time="08:45",
            week_type="ALL",
            subgroup="1",
        )
    assert "уже существует" in str(exc.value) or "пересекается" in str(exc.value)

    # Adding whole-class (None) overlapping with 'boys' - CONFLICT
    with pytest.raises(LessonConflictError) as exc:
        await validate_lesson_conflict(
            db=db_session,
            day_of_week=1,
            lesson_number=1,
            start_time="08:00",
            end_time="08:45",
            week_type="ALL",
            subgroup=None,
        )
    assert "уже существует" in str(exc.value) or "пересекается" in str(exc.value)


@pytest.mark.asyncio
async def test_admin_creates_and_updates_user_gender_subgroup(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    # Admin creates user with gender_subgroup="boys"
    res = await client.post(
        "/admin/users",
        data={
            "username": "boy_student",
            "password": "Password123",
            "subgroup": "1",
            "gender_subgroup": "boys",
        },
        headers=auth_headers,
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert "boy_student" in res.text

    # Verify user in DB
    user_stmt = select(User).where(User.username == "boy_student")
    u = (await db_session.execute(user_stmt)).scalar_one()
    assert u.subgroup == 1
    assert u.gender_subgroup == "boys"

    # Admin updates gender_subgroup to "girls" via POST /admin/users/{user_id}/gender-subgroup
    res_update = await client.post(
        f"/admin/users/{u.id}/gender-subgroup",
        data={"gender_subgroup": "girls"},
        headers=auth_headers,
        follow_redirects=True,
    )
    assert res_update.status_code == 200
    await db_session.refresh(u)
    assert u.gender_subgroup == "girls"

    # Admin resets gender_subgroup to None
    res_reset = await client.post(
        f"/admin/users/{u.id}/gender-subgroup",
        data={"gender_subgroup": ""},
        headers=auth_headers,
        follow_redirects=True,
    )
    assert res_reset.status_code == 200
    await db_session.refresh(u)
    assert u.gender_subgroup is None

    # Invalid gender_subgroup rejected
    res_invalid = await client.post(
        "/admin/users",
        data={
            "username": "invalid_gender_user",
            "password": "Password123",
            "gender_subgroup": "alien",
        },
        headers=auth_headers,
        follow_redirects=True,
    )
    assert res_invalid.status_code == 400
    assert "Неверное значение гендерной подгруппы" in res_invalid.text


@pytest.mark.asyncio
async def test_homework_and_lesson_gender_isolation(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
):
    # Create subject with teachers/rooms for both subgroups (boys/girls)
    sub = Subject(
        name="Труд",
        room="Мастерская",
        teacher_name="Иванов И.И.",
        room2="Кулинария",
        teacher2_name="Петрова П.П.",
    )
    # Ivan (subgroup=1, gender_subgroup="boys")
    ivan = User(
        username="ivan_boy",
        hashed_password=hash_password("pass123"),
        subgroup=1,
        gender_subgroup="boys",
        is_active=True,
    )
    # Anna (subgroup=2, gender_subgroup="girls")
    anna = User(
        username="anna_girl",
        hashed_password=hash_password("pass123"),
        subgroup=2,
        gender_subgroup="girls",
        is_active=True,
    )
    db_session.add_all([sub, ivan, anna])
    await db_session.commit()
    await db_session.refresh(sub)
    await db_session.refresh(ivan)
    await db_session.refresh(anna)

    token_ivan = create_access_token({"sub": str(ivan.id), "pwd": get_password_fingerprint(ivan.hashed_password)})
    token_anna = create_access_token({"sub": str(anna.id), "pwd": get_password_fingerprint(anna.hashed_password)})
    headers_ivan = {"Authorization": f"Bearer {token_ivan}"}
    headers_anna = {"Authorization": f"Bearer {token_anna}"}

    # Parallel lessons: Monday lesson 1 for boys (Мастерская) and girls (Кулинария)
    l_boys = Lesson(
        subject_id=sub.id,
        day_of_week=1,
        lesson_number=1,
        start_time="08:00",
        end_time="08:45",
        week_type="ALL",
        subgroup="boys",
    )
    l_girls = Lesson(
        subject_id=sub.id,
        day_of_week=1,
        lesson_number=1,
        start_time="08:00",
        end_time="08:45",
        week_type="ALL",
        subgroup="girls",
    )
    db_session.add_all([l_boys, l_girls])
    await db_session.commit()
    await db_session.refresh(l_boys)
    await db_session.refresh(l_girls)

    assert l_boys.effective_room == "Мастерская"
    assert l_boys.effective_teacher_name == "Иванов И.И."
    assert l_girls.effective_room == "Кулинария"
    assert l_girls.effective_teacher_name == "Петрова П.П."

    # Homework for boys
    hw_boys = Homework(
        subject_id=sub.id,
        lesson_id=l_boys.id,
        title="Выточить деталь",
        due_date=date(2026, 11, 2),
        subgroup="boys",
    )
    # Homework for girls
    hw_girls = Homework(
        subject_id=sub.id,
        lesson_id=l_girls.id,
        title="Сшить фартук",
        due_date=date(2026, 11, 2),
        subgroup="girls",
    )
    db_session.add_all([hw_boys, hw_girls])
    await db_session.commit()
    await db_session.refresh(hw_boys)
    await db_session.refresh(hw_girls)

    # API: Ivan queries homework
    res_ivan = await client.get("/api/v1/homework", headers=headers_ivan)
    assert res_ivan.status_code == 200
    ivan_hw_titles = [h["title"] for h in res_ivan.json()]
    assert "Выточить деталь" in ivan_hw_titles
    assert "Сшить фартук" not in ivan_hw_titles

    # GET single homework endpoint for own subgroup (str vs int bug check)
    res_single_ivan = await client.get(f"/api/v1/homework/{hw_boys.id}", headers=headers_ivan)
    assert res_single_ivan.status_code == 200
    assert res_single_ivan.json()["title"] == "Выточить деталь"

    # GET single homework endpoint for foreign subgroup
    res_single_anna_forbidden = await client.get(f"/api/v1/homework/{hw_boys.id}", headers=headers_anna)
    assert res_single_anna_forbidden.status_code == 404

    # Option Б verification: student with academic subgroup 1 and NO gender subgroup specified
    # sees whole class, subgroup 1, and ALL gendered lessons/homework (boys and girls)
    # but does NOT see subgroup 2
    student_ungendered = User(
        username="ungendered_sub1",
        hashed_password=hash_password("pass123"),
        subgroup=1,
        gender_subgroup=None,
        is_active=True,
    )
    db_session.add(student_ungendered)
    await db_session.commit()
    await db_session.refresh(student_ungendered)
    token_ungendered = create_access_token(
        {"sub": str(student_ungendered.id), "pwd": get_password_fingerprint(student_ungendered.hashed_password)}
    )
    headers_ungendered = {"Authorization": f"Bearer {token_ungendered}"}

    res_ungendered_list = await client.get("/api/v1/homework", headers=headers_ungendered)
    assert res_ungendered_list.status_code == 200
    ungendered_titles = [h["title"] for h in res_ungendered_list.json()]
    assert "Выточить деталь" in ungendered_titles
    assert "Сшить фартук" in ungendered_titles

    # API: Anna queries homework
    res_anna = await client.get("/api/v1/homework", headers=headers_anna)
    assert res_anna.status_code == 200
    anna_hw_titles = [h["title"] for h in res_anna.json()]
    assert "Сшить фартук" in anna_hw_titles
    assert "Выточить деталь" not in anna_hw_titles

    # Security: Ivan attempts to toggle Anna's homework (subgroup="girls") -> 404 (hidden/isolated from other subgroups)
    res_toggle_forbidden = await client.patch(
        f"/api/v1/homework/{hw_girls.id}/status",
        headers=headers_ivan,
        json={"status": "DONE"},
    )
    assert res_toggle_forbidden.status_code == 404

    # Security: Anna attempts to toggle Ivan's homework (subgroup="boys") via Web -> 403 Forbidden
    res_web_toggle_forbidden = await client.post(
        f"/homework/{hw_boys.id}/toggle",
        headers=headers_anna,
    )
    assert res_web_toggle_forbidden.status_code == 403

    # Security: Ivan attempts to edit Anna's homework -> 403
    res_edit_forbidden = await client.put(
        f"/api/v1/homework/{hw_girls.id}",
        headers=headers_ivan,
        json={"title": "Взлом ДЗ", "due_date": "2026-11-02", "subgroup": "girls"},
    )
    assert res_edit_forbidden.status_code == 403


@pytest.mark.asyncio
async def test_clone_lesson_boys_girls(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    sub = Subject(
        name="Технология 2",
        room="101",
        room2="202",
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)

    # 1. Create a lesson for boys on Wednesday
    res_create = await client.post(
        "/api/v1/schedule",
        headers=auth_headers,
        json={
            "subject_id": sub.id,
            "day_of_week": 3,
            "lesson_number": 2,
            "start_time": "08:55",
            "end_time": "09:40",
            "subgroup": "boys",
            "room": "101",
        },
    )
    assert res_create.status_code == 201
    boys_lesson_id = res_create.json()["id"]

    # 2. Admin clones boys lesson -> creates counterpart for girls
    res_clone = await client.post(
        f"/api/v1/schedule/{boys_lesson_id}/clone",
        headers=auth_headers,
    )
    assert res_clone.status_code == 201
    cloned_data = res_clone.json()
    assert cloned_data["subgroup"] == "girls"
    assert cloned_data["room"] == "202"  # Set from subject.room2

    # 3. Cloning again fails because girls counterpart already exists
    res_clone_fail = await client.post(
        f"/api/v1/schedule/{boys_lesson_id}/clone",
        headers=auth_headers,
    )
    assert res_clone_fail.status_code == 422

    # 4. Web clone for girls -> creates counterpart for boys
    sub_pe = Subject(name="Физкультура", room="Спортзал 1", room2="Спортзал 2")
    db_session.add(sub_pe)
    await db_session.commit()
    await db_session.refresh(sub_pe)

    lesson_girls = Lesson(
        subject_id=sub_pe.id,
        day_of_week=4,
        lesson_number=3,
        start_time="09:50",
        end_time="10:35",
        week_type="ALL",
        subgroup="girls",
        room="Спортзал 2",
    )
    db_session.add(lesson_girls)
    await db_session.commit()
    await db_session.refresh(lesson_girls)

    res_web_clone = await client.post(
        f"/schedule/{lesson_girls.id}/clone",
        headers={**auth_headers, "Accept": "application/json"},
    )
    assert res_web_clone.status_code == 200
    assert res_web_clone.json()["ok"] is True
    # Verify in DB
    lessons_stmt = select(Lesson).where(Lesson.subject_id == sub_pe.id, Lesson.day_of_week == 4)
    pe_lessons = (await db_session.execute(lessons_stmt)).scalars().all()
    assert len(pe_lessons) == 2
    subs = {l.subgroup for l in pe_lessons}
    assert subs == {"boys", "girls"}
    boys_l = next(l for l in pe_lessons if l.subgroup == "boys")
    assert boys_l.room == "Спортзал 1"


@pytest.mark.asyncio
async def test_admin_subgroup_with_gender_and_user_gender_display_hidden(
    client: AsyncClient,
    db_session: AsyncSession,
):
    sub_math = Subject(name="Математика")
    sub_eng = Subject(name="Английский")
    sub_tech = Subject(name="Технология")
    db_session.add_all([sub_math, sub_eng, sub_tech])
    await db_session.commit()
    await db_session.refresh(sub_math)
    await db_session.refresh(sub_eng)
    await db_session.refresh(sub_tech)

    # Monday:
    # Lesson 1: Math for Subgroup 1, English for Subgroup 2
    l_math_sub1 = Lesson(
        subject_id=sub_math.id, day_of_week=1, lesson_number=1,
        start_time="08:00", end_time="08:45", week_type="ALL", subgroup="1",
    )
    l_eng_sub2 = Lesson(
        subject_id=sub_eng.id, day_of_week=1, lesson_number=1,
        start_time="08:00", end_time="08:45", week_type="ALL", subgroup="2",
    )
    # Lesson 2: Technology for boys, Technology for girls
    l_tech_boys = Lesson(
        subject_id=sub_tech.id, day_of_week=1, lesson_number=2,
        start_time="08:55", end_time="09:40", week_type="ALL", subgroup="boys",
    )
    l_tech_girls = Lesson(
        subject_id=sub_tech.id, day_of_week=1, lesson_number=2,
        start_time="08:55", end_time="09:40", week_type="ALL", subgroup="girls",
    )
    db_session.add_all([l_math_sub1, l_eng_sub2, l_tech_boys, l_tech_girls])

    # Admin: in subgroup 1 and gender "boys"
    admin_boy = User(
        username="admin_boy_1",
        hashed_password=hash_password("adminpass123"),
        is_active=True,
        is_admin=True,
        subgroup=1,
        gender_subgroup="boys",
    )
    # Student: in subgroup 1 and gender "boys"
    student_boy = User(
        username="student_boy_1",
        hashed_password=hash_password("pass123"),
        is_active=True,
        is_admin=False,
        subgroup=1,
        gender_subgroup="boys",
    )
    db_session.add_all([admin_boy, student_boy])
    await db_session.commit()
    await db_session.refresh(admin_boy)
    await db_session.refresh(student_boy)

    t_admin = create_access_token({"sub": str(admin_boy.id), "pwd": get_password_fingerprint(admin_boy.hashed_password)})
    t_student = create_access_token({"sub": str(student_boy.id), "pwd": get_password_fingerprint(student_boy.hashed_password)})
    headers_admin = {"Authorization": f"Bearer {t_admin}"}
    headers_student = {"Authorization": f"Bearer {t_student}"}

    target_monday = "2026-10-26"

    # 1. Admin views dashboard with subgroup 1 (default or ?subgroup=1)
    # Must show: Math (subgroup 1) AND Technology for boys
    # Must NOT show: Technology for girls (only in "all" or "girls"), English (subgroup 2)
    r_admin_default = await client.get(f"/?date={target_monday}", headers=headers_admin)
    assert r_admin_default.status_code == 200
    assert f'id="lesson-card-{l_math_sub1.id}"' in r_admin_default.text
    assert f'id="lesson-card-{l_tech_boys.id}"' in r_admin_default.text
    assert f'id="lesson-card-{l_eng_sub2.id}"' not in r_admin_default.text
    assert f'id="lesson-card-{l_tech_girls.id}"' not in r_admin_default.text

    # Explicit ?subgroup=1
    r_admin_sub1 = await client.get(f"/?date={target_monday}&subgroup=1", headers=headers_admin)
    assert f'id="lesson-card-{l_math_sub1.id}"' in r_admin_sub1.text
    assert f'id="lesson-card-{l_tech_boys.id}"' in r_admin_sub1.text
    assert f'id="lesson-card-{l_tech_girls.id}"' not in r_admin_sub1.text

    # Admin views ?subgroup=all -> shows everything (boys and girls)
    r_admin_all = await client.get(f"/?date={target_monday}&subgroup=all", headers=headers_admin)
    assert f'id="lesson-card-{l_math_sub1.id}"' in r_admin_all.text
    assert f'id="lesson-card-{l_eng_sub2.id}"' in r_admin_all.text
    assert f'id="lesson-card-{l_tech_boys.id}"' in r_admin_all.text
    assert f'id="lesson-card-{l_tech_girls.id}"' in r_admin_all.text

    # Admin views ?subgroup=girls -> shows Technology for girls, NOT Technology for boys
    r_admin_girls = await client.get(f"/?date={target_monday}&subgroup=girls", headers=headers_admin)
    assert f'id="lesson-card-{l_tech_girls.id}"' in r_admin_girls.text
    assert f'id="lesson-card-{l_tech_boys.id}"' not in r_admin_girls.text

    # 2. Regular student view:
    # Must show Math and Technology for boys
    r_student = await client.get(f"/?date={target_monday}", headers=headers_student)
    assert r_student.status_code == 200
    assert f'id="lesson-card-{l_math_sub1.id}"' in r_student.text
    assert f'id="lesson-card-{l_tech_boys.id}"' in r_student.text
    assert f'id="lesson-card-{l_tech_girls.id}"' not in r_student.text

    # User's gender must NOT be displayed in header, only subgroup:
    # "1 подгруппа" is present, but gender pill is absent
    assert "1 подгруппа" in r_student.text
    # Check that Мальчики is not in user profile header badge
    assert '<div class="inline-flex items-center gap-1 px-2.5 py-1 rounded-xl bg-cyan-500/10' not in r_student.text

    # Homework page: gender pill absent for regular student
    r_hw_student = await client.get("/homework", headers=headers_student)
    assert r_hw_student.status_code == 200
    assert "1 подгруппа" in r_hw_student.text
    assert '<span class="inline-flex items-center gap-1 px-3 py-1 rounded-xl bg-cyan-500/10' not in r_hw_student.text



