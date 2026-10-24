import pytest
from httpx import AsyncClient

from locus.models.subject import Subject
from locus.models.user import User
from tests.helpers import add_homework


@pytest.mark.asyncio
async def test_pwa_manifest_and_static(client: AsyncClient):
    """Test PWA manifest is served correctly with standalone display."""
    res = await client.get("/static/manifest.json")
    assert res.status_code == 200
    data = res.json()
    assert data["display"] == "standalone"
    assert data["short_name"] == "Locus"
    assert len(data["icons"]) >= 2


@pytest.mark.asyncio
async def test_unauthenticated_redirect_to_login(client: AsyncClient):
    """Unauthenticated visitor trying to access dashboard should be redirected to /login."""
    res = await client.get("/", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["Location"] == "/login"

    # HTMX request should receive HX-Redirect header
    res_htmx = await client.get("/", headers={"HX-Request": "true"})
    assert res_htmx.status_code == 200
    assert res_htmx.headers.get("HX-Redirect") == "/login"


@pytest.mark.asyncio
async def test_authenticated_dashboard(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
):
    """Authenticated user should see the dashboard page."""
    from locus.config import get_settings
    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    res = await client.get("/")
    assert res.status_code == 200
    assert "Расписание на " in res.text
    assert "Locus" in res.text


@pytest.mark.asyncio
async def test_homework_page_hides_past_due_tasks(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    test_subject: Subject,
    db_session,
):
    """The homework tab should only list tasks due today or later."""
    from datetime import timedelta

    from locus.config import get_settings
    from locus.constants import HomeworkStatus, get_current_date

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    today = get_current_date()
    await add_homework(
        db_session,
        test_user,
        subject_id=test_subject.id,
        title="Просроченная задача",
        due_date=today - timedelta(days=1),
    )
    await add_homework(
        db_session,
        test_user,
        subject_id=test_subject.id,
        title="Старая выполненная",
        due_date=today - timedelta(days=3),
        status=HomeworkStatus.DONE.value,
    )
    await add_homework(
        db_session,
        test_user,
        subject_id=test_subject.id,
        title="Задача на сегодня",
        due_date=today,
    )
    await add_homework(
        db_session,
        test_user,
        subject_id=test_subject.id,
        title="Будущая задача",
        due_date=today + timedelta(days=2),
    )

    res = await client.get("/homework")
    assert res.status_code == 200
    assert "Задача на сегодня" in res.text
    assert "Будущая задача" in res.text
    assert "Просроченная задача" not in res.text
    assert "Старая выполненная" not in res.text

    done_res = await client.get("/homework?filter=done")
    assert done_res.status_code == 200
    assert "Старая выполненная" not in done_res.text


@pytest.mark.asyncio
async def test_dashboard_offers_next_lesson_quick_action(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    test_subject: Subject,
    db_session,
    monkeypatch,
):
    """The dashboard modal gets the same quick action when today is selected."""
    from datetime import datetime, time, timedelta
    from zoneinfo import ZoneInfo

    from locus.config import get_settings
    from locus.constants import get_current_date
    from locus.models.lesson import Lesson

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    today = get_current_date()
    lesson = Lesson(
        subject_id=test_subject.id,
        day_of_week=today.isoweekday(),
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)

    fixed_now = datetime.combine(
        today,
        time(9, 0),
        tzinfo=ZoneInfo("Asia/Almaty"),
    )
    monkeypatch.setattr(
        "locus.web.dashboard_routes.get_current_datetime",
        lambda: fixed_now,
    )

    res = await client.get("/")
    assert res.status_code == 200
    assert "На следующий урок" in res.text
    assert "data-next-lesson-btn" in res.text
    assert f'data-lesson-id="{lesson.id}"' in res.text
    assert f'data-subject-id="{test_subject.id}"' in res.text
    assert f'data-due-date="{(today + timedelta(days=7)).isoformat()}"' in res.text
    assert 'data-auto-apply="true"' in res.text


@pytest.mark.asyncio
async def test_homework_page_offers_next_lesson_quick_action(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    test_subject: Subject,
    db_session,
    monkeypatch,
):
    """During a lesson the add-homework modal offers the current subject's next date."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from locus.config import get_settings
    from locus.models.lesson import Lesson

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    fixed_now = datetime(2026, 10, 22, 9, 0, tzinfo=ZoneInfo("Asia/Almaty"))
    lesson = Lesson(
        subject_id=test_subject.id,
        day_of_week=4,  # Thursday
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)

    monkeypatch.setattr(
        "locus.web.homework_routes.get_current_datetime",
        lambda: fixed_now,
    )

    res = await client.get("/homework")
    assert res.status_code == 200
    assert "На следующий урок" in res.text
    assert "data-next-lesson-btn" in res.text
    assert f'data-lesson-id="{lesson.id}"' in res.text
    assert f'data-subject-id="{test_subject.id}"' in res.text
    assert 'data-due-date="2026-10-29"' in res.text
    assert 'data-auto-apply="true"' in res.text
    assert "29 октября в 08:30" in res.text


@pytest.mark.asyncio
async def test_login_page(client: AsyncClient):
    """Login page should render and use a username field."""
    res_login = await client.get("/login")
    assert res_login.status_code == 200
    assert "Вход в Locus" in res_login.text
    assert 'name="username"' in res_login.text
    assert "/register" not in res_login.text


@pytest.mark.asyncio
async def test_lesson_modal_and_inline_homework(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    test_subject: Subject,
    db_session,
):
    """Test clicking a lesson opens modal and saves/deletes inline homework with OOB updates."""
    from locus.config import get_settings
    from locus.constants import HomeworkStatus
    from locus.models.homework import Homework
    from locus.models.lesson import Lesson

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    # 1. Create lesson on Wednesday
    lesson = Lesson(
        subject_id=test_subject.id,
        day_of_week=3,
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
        room="304",
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)

    target_date = "2026-10-21"  # Wednesday

    # 2. Open lesson modal
    res_modal = await client.get(f"/dashboard/lesson/{lesson.id}/modal?date={target_date}")
    assert res_modal.status_code == 200
    assert "Алгебра" in res_modal.text
    assert "Иванова С.П." in res_modal.text
    assert "+79990001122" in res_modal.text
    assert "https://wa.me/79990001122" in res_modal.text
    assert "WhatsApp" in res_modal.text
    assert "08:30 — 09:15" in res_modal.text
    assert "Каб. 304" in res_modal.text
    assert "Ср, 21 октября" in res_modal.text
    assert "lesson-detail-modal" in res_modal.text

    # 3. Save homework via inline modal form
    res_save = await client.post(
        f"/dashboard/lesson/{lesson.id}/homework?date={target_date}",
        data={
            "title": "§ 12, № 45-48",
            "is_done": "true",
        },
    )
    assert res_save.status_code == 200
    assert 'hx-swap-oob="outerHTML"' in res_save.text
    assert f'id="lesson-card-{lesson.id}"' in res_save.text
    assert f'id="m-lesson-card-{lesson.id}-3"' in res_save.text
    assert "§ 12, № 45-48" in res_save.text

    # Verify saved in DB
    from sqlalchemy import select

    from locus.homework_status import get_completion

    hw_res = await db_session.execute(
        select(Homework).where(Homework.lesson_id == lesson.id)
    )
    saved_hw = hw_res.scalar_one_or_none()
    assert saved_hw is not None
    assert saved_hw.title == "§ 12, № 45-48"
    completion = await get_completion(db_session, saved_hw.id, test_user.id)
    assert completion is not None
    assert completion.status == HomeworkStatus.DONE.value

    # 4. Delete homework via clearing title in modal ("пустое, значит ничего не задано")
    res_delete = await client.post(
        f"/dashboard/lesson/{lesson.id}/homework?date={target_date}",
        data={
            "hw_id": saved_hw.id,
            "title": "",
        },
    )
    assert res_delete.status_code == 200
    assert 'hx-swap-oob="outerHTML"' in res_delete.text
    assert "Домашнего задания нет" in res_delete.text

    # Verify deleted from DB
    hw_del_res = await db_session.execute(
        select(Homework).where(Homework.id == saved_hw.id)
    )
    assert hw_del_res.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_paired_lessons_no_homework_cross_contamination(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    test_subject: Subject,
    db_session,
):
    """Homework from second lesson of same subject should not leak into first lesson modal."""
    from locus.config import get_settings
    from locus.models.lesson import Lesson
    from datetime import date

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    # 1. Create two Algebra lessons on the same Wednesday
    lesson1 = Lesson(
        subject_id=test_subject.id,
        day_of_week=3,
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
    )
    lesson2 = Lesson(
        subject_id=test_subject.id,
        day_of_week=3,
        lesson_number=2,
        start_time="09:25",
        end_time="10:10",
    )
    db_session.add_all([lesson1, lesson2])
    await db_session.commit()
    await db_session.refresh(lesson1)
    await db_session.refresh(lesson2)

    target_date = "2026-10-21"

    # 2. Add homework specifically to lesson 2
    await add_homework(
        db_session,
        test_user,
        subject_id=test_subject.id,
        lesson_id=lesson2.id,
        title="Задание для второго урока",
        due_date=date.fromisoformat(target_date),
    )

    # 3. Open modal for lesson 1
    res_modal1 = await client.get(f"/dashboard/lesson/{lesson1.id}/modal?date={target_date}")
    assert res_modal1.status_code == 200
    # Lesson 2's homework title must NOT appear in lesson 1's modal
    assert "Задание для второго урока" not in res_modal1.text
    assert 'modal-hw-title' in res_modal1.text

    # 4. Open modal for lesson 2
    res_modal2 = await client.get(f"/dashboard/lesson/{lesson2.id}/modal?date={target_date}")
    assert res_modal2.status_code == 200
    assert "Задание для второго урока" in res_modal2.text


@pytest.mark.asyncio
async def test_unassigned_homework_deletion_from_modal(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    test_subject: Subject,
    db_session,
):
    """Deleting an unassigned homework from lesson modal should emit OOB deletion for dashboard list."""
    from locus.config import get_settings
    from locus.models.lesson import Lesson
    from datetime import date

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    lesson = Lesson(
        subject_id=test_subject.id,
        day_of_week=3,
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)

    target_date = "2026-10-21"

    # Create unassigned homework for this subject and date (lesson_id=None)
    unassigned_hw = await add_homework(
        db_session,
        test_user,
        subject_id=test_subject.id,
        lesson_id=None,
        title="Нераспределенное ДЗ",
        due_date=date.fromisoformat(target_date),
    )

    # Modal should show this unassigned homework
    res_modal = await client.get(f"/dashboard/lesson/{lesson.id}/modal?date={target_date}")
    assert res_modal.status_code == 200
    assert "Нераспределенное ДЗ" in res_modal.text

    # Delete it via modal by clearing title ("пустое, значит ничего не задано")
    res_del = await client.post(
        f"/dashboard/lesson/{lesson.id}/homework?date={target_date}",
        data={"hw_id": unassigned_hw.id, "title": ""},
    )
    assert res_del.status_code == 200
    assert f'id="desktop-unassigned-hw-{unassigned_hw.id}" hx-swap-oob="delete"' in res_del.text
    assert f'id="mobile-unassigned-hw-{unassigned_hw.id}-3" hx-swap-oob="delete"' in res_del.text


@pytest.mark.asyncio
async def test_unassigned_homework_saved_in_modal_removes_unassigned_card(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    test_subject: Subject,
    db_session,
):
    """Saving an unassigned homework in lesson modal binds it to lesson and removes unassigned card."""
    from locus.config import get_settings
    from locus.constants import HomeworkStatus
    from locus.models.homework import Homework
    from locus.models.lesson import Lesson
    from datetime import date
    from sqlalchemy import select

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    lesson = Lesson(
        subject_id=test_subject.id,
        day_of_week=3,
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)

    target_date = "2026-10-21"

    unassigned_hw = await add_homework(
        db_session,
        test_user,
        subject_id=test_subject.id,
        lesson_id=None,
        title="Нераспределенная задача",
        due_date=date.fromisoformat(target_date),
    )

    # Save with non-empty title -> binds to lesson and removes unassigned card
    res_save = await client.post(
        f"/dashboard/lesson/{lesson.id}/homework?date={target_date}",
        data={"hw_id": unassigned_hw.id, "title": "Привязанная задача"},
    )
    assert res_save.status_code == 200
    assert f'id="desktop-unassigned-hw-{unassigned_hw.id}" hx-swap-oob="delete"' in res_save.text
    assert f'id="mobile-unassigned-hw-{unassigned_hw.id}-3" hx-swap-oob="delete"' in res_save.text

    # Verify lesson_id is now bound
    res_check = await db_session.execute(select(Homework).where(Homework.id == unassigned_hw.id))
    hw_updated = res_check.scalar_one()
    assert hw_updated.lesson_id == lesson.id
    assert hw_updated.title == "Привязанная задача"


@pytest.mark.asyncio
async def test_non_admin_web_subjects_and_schedule_restrictions(
    client: AsyncClient,
    regular_user: User,
    regular_token: str,
    test_subject: Subject,
    db_session,
):
    """Regular user cannot create or delete subjects/schedule via web routes."""
    from locus.config import get_settings
    from locus.models.lesson import Lesson

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, regular_token)

    # 1. Subjects view works, but add button is hidden
    res_subj = await client.get("/subjects")
    assert res_subj.status_code == 200
    assert "+ Новый предмет" not in res_subj.text
    assert test_subject.name in res_subj.text

    # 2. Creating a subject returns 403
    res_create_subj = await client.post("/subjects", data={"name": "Химия"})
    assert res_create_subj.status_code == 403

    # 3. Deleting a subject returns 403
    res_del_subj = await client.delete(f"/subjects/{test_subject.id}")
    assert res_del_subj.status_code == 403

    # 4. Schedule view works, but add button is hidden
    lesson = Lesson(
        subject_id=test_subject.id,
        day_of_week=1,
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)

    res_sched = await client.get("/schedule")
    assert res_sched.status_code == 200
    assert "Добавить урок" not in res_sched.text

    # 5. Creating a lesson returns 403
    res_create_lesson = await client.post(
        "/schedule",
        data={
            "subject_id": test_subject.id,
            "day_of_week": 2,
            "lesson_number": 1,
            "start_time": "08:30",
            "end_time": "09:15",
        },
    )
    assert res_create_lesson.status_code == 403

    # 6. Deleting a lesson returns 403
    res_del_lesson = await client.delete(f"/schedule/{lesson.id}")
    assert res_del_lesson.status_code == 403


@pytest.mark.asyncio
async def test_web_shared_homework_and_personal_completion(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    regular_user: User,
    regular_token: str,
    test_subject: Subject,
    db_session,
):
    """Homework is shared, status is personal, any user can delete shared homework."""
    from datetime import date, timedelta
    from sqlalchemy import select
    from locus.config import get_settings
    from locus.models.homework import Homework

    settings = get_settings()
    target_date = date.today() + timedelta(days=1)
    if target_date.isoweekday() == 7:
        target_date += timedelta(days=1)
    tomorrow = target_date.isoformat()

    # 1. Regular user creates a shared homework via web
    client.cookies.set(settings.COOKIE_NAME, regular_token)
    res_create = await client.post(
        "/homework",
        data={
            "subject_id": test_subject.id,
            "title": "Общее эссе по литературе",
            "due_date": tomorrow,
        },
        follow_redirects=False,
    )
    assert res_create.status_code == 303

    # Find the created homework
    res_hw = await db_session.execute(
        select(Homework).where(Homework.title == "Общее эссе по литературе")
    )
    hw = res_hw.scalar_one()

    # 2. Admin logs in and sees the homework in /homework
    client.cookies.set(settings.COOKIE_NAME, auth_token)
    res_admin_list = await client.get("/homework")
    assert res_admin_list.status_code == 200
    assert "Общее эссе по литературе" in res_admin_list.text

    # Admin marks it DONE
    res_toggle = await client.post(f"/homework/{hw.id}/toggle")
    assert res_toggle.status_code == 200
    assert "hw-done-title" in res_toggle.text

    # Admin filter=done contains the homework
    res_admin_done = await client.get("/homework?filter=done")
    assert res_admin_done.status_code == 200
    assert "Общее эссе по литературе" in res_admin_done.text

    # 3. Regular user logs in: for them status is still TODO
    client.cookies.set(settings.COOKIE_NAME, regular_token)
    res_reg_done = await client.get("/homework?filter=done")
    assert res_reg_done.status_code == 200
    assert "Общее эссе по литературе" not in res_reg_done.text

    res_reg_todo = await client.get("/homework?filter=todo")
    assert res_reg_todo.status_code == 200
    assert "Общее эссе по литературе" in res_reg_todo.text

    # 4. Regular user deletes the homework
    res_del = await client.delete(f"/homework/{hw.id}")
    assert res_del.status_code == 200

    # 5. Admin no longer sees it
    client.cookies.set(settings.COOKIE_NAME, auth_token)
    res_admin_check = await client.get("/homework")
    assert "Общее эссе по литературе" not in res_admin_check.text


@pytest.mark.asyncio
async def test_multiple_homeworks_on_same_lesson_does_not_crash_modal_save(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    test_subject: Subject,
    db_session,
):
    """When multiple homeworks exist for the same lesson and date, saving does not crash with MultipleResultsFound."""
    from datetime import date
    from locus.config import get_settings
    from locus.models.lesson import Lesson

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    lesson = Lesson(
        subject_id=test_subject.id,
        day_of_week=4,
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)

    target_date = "2026-10-22"
    # Create two homeworks for the same lesson and date
    hw1 = await add_homework(
        db_session,
        test_user,
        subject_id=test_subject.id,
        lesson_id=lesson.id,
        title="Первое задание",
        due_date=date.fromisoformat(target_date),
    )
    hw2 = await add_homework(
        db_session,
        test_user,
        subject_id=test_subject.id,
        lesson_id=lesson.id,
        title="Второе задание",
        due_date=date.fromisoformat(target_date),
    )

    # Save via modal without passing hw_id -> should succeed without 500
    res = await client.post(
        f"/dashboard/lesson/{lesson.id}/homework?date={target_date}",
        data={"title": "Обновленное задание"},
    )
    assert res.status_code == 200
    assert "Обновленное задание" in res.text


@pytest.mark.asyncio
async def test_dashboard_weekend_advances_to_next_monday(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    monkeypatch,
):
    from datetime import date
    from locus.config import get_settings

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    # 1. Saturday without lessons -> opens upcoming Monday (2026-10-26)
    saturday = date(2026, 10, 24)
    monkeypatch.setattr("locus.web.dashboard_routes.get_current_date", lambda: saturday)
    monkeypatch.setattr("locus.constants.get_current_date", lambda: saturday)

    res_sat = await client.get("/")
    assert res_sat.status_code == 200
    assert "Понедельник" in res_sat.text
    assert "26 октября" in res_sat.text

    # 2. Sunday without lessons -> opens upcoming Monday (2026-10-26)
    sunday = date(2026, 10, 25)
    monkeypatch.setattr("locus.web.dashboard_routes.get_current_date", lambda: sunday)
    monkeypatch.setattr("locus.constants.get_current_date", lambda: sunday)

    res_sun = await client.get("/")
    assert res_sun.status_code == 200
    assert "Понедельник" in res_sun.text
    assert "26 октября" in res_sun.text

    # 3. Explicit date param overrides default behavior
    res_explicit = await client.get("/?date=2026-10-24")
    assert res_explicit.status_code == 200
    assert "Суббота" in res_explicit.text
    assert "24 октября" in res_explicit.text


@pytest.mark.asyncio
async def test_vacation_web_crud(
    client: AsyncClient,
    test_user: User,
    regular_user: User,
    auth_token: str,
    regular_token: str,
    db_session,
):
    from locus.config import get_settings
    from locus.models.vacation import Vacation
    from sqlalchemy import select

    settings = get_settings()

    # 1. Non-admin cannot create vacation via web
    client.cookies.set(settings.COOKIE_NAME, regular_token)
    res_forbidden = await client.post(
        "/schedule/vacations",
        data={
            "name": "Недоступные каникулы",
            "start_date": "2026-10-26",
            "end_date": "2026-11-03",
        },
        follow_redirects=False,
    )
    assert res_forbidden.status_code == 403

    # 2. Admin creates vacation via web form
    client.cookies.set(settings.COOKIE_NAME, auth_token)
    res_create = await client.post(
        "/schedule/vacations",
        data={
            "name": "Зимние каникулы",
            "start_date": "2026-12-28",
            "end_date": "2027-01-10",
        },
        follow_redirects=False,
    )
    assert res_create.status_code == 303
    assert res_create.headers["Location"] == "/schedule"

    # Verify vacation in DB
    vac_res = await db_session.execute(select(Vacation).where(Vacation.name == "Зимние каникулы"))
    vac = vac_res.scalars().first()
    assert vac is not None
    assert str(vac.start_date) == "2026-12-28"
    assert str(vac.end_date) == "2027-01-10"

    # 2.1. Overlapping vacation returns 400
    res_overlap = await client.post(
        "/schedule/vacations",
        data={
            "name": "Новогодние",
            "start_date": "2026-12-30",
            "end_date": "2027-01-05",
        },
        follow_redirects=False,
    )
    assert res_overlap.status_code == 400
    assert "пересекаются" in res_overlap.json()["detail"]

    # 3. Schedule page renders vacation section
    res_page = await client.get("/schedule")
    assert res_page.status_code == 200
    assert "Школьные каникулы" in res_page.text
    assert "Зимние каникулы" in res_page.text
    assert "28.12.2026" in res_page.text

    # 4. Admin edits vacation
    res_edit = await client.post(
        f"/schedule/vacations/{vac.id}/edit",
        data={
            "name": "Большие зимние каникулы",
            "start_date": "2026-12-25",
            "end_date": "2027-01-11",
        },
        follow_redirects=False,
    )
    assert res_edit.status_code == 303
    await db_session.refresh(vac)
    assert vac.name == "Большие зимние каникулы"
    assert str(vac.start_date) == "2026-12-25"

    # 5. Admin deletes vacation
    res_del = await client.delete(f"/schedule/vacations/{vac.id}")
    assert res_del.status_code == 200
    vac_deleted = await db_session.get(Vacation, vac.id)
    assert vac_deleted is None

    # 6. Fallback edit GET routes: non-admin gets 403, admin gets redirected
    client.cookies.set(settings.COOKIE_NAME, regular_token)
    res_fallback_forbidden = await client.get("/schedule/vacations/1/edit", follow_redirects=False)
    assert res_fallback_forbidden.status_code == 403

    res_subj_fallback_forbidden = await client.get("/subjects/1/edit", follow_redirects=False)
    assert res_subj_fallback_forbidden.status_code == 403

    client.cookies.set(settings.COOKIE_NAME, auth_token)
    res_fallback_admin = await client.get("/schedule/vacations/1/edit", follow_redirects=False)
    assert res_fallback_admin.status_code == 303
    assert res_fallback_admin.headers["Location"] == "/schedule"

    res_subj_fallback_admin = await client.get("/subjects/1/edit", follow_redirects=False)
    assert res_subj_fallback_admin.status_code == 303
    assert res_subj_fallback_admin.headers["Location"] == "/subjects"


@pytest.mark.asyncio
async def test_dashboard_vacation_banner_and_weekend_stay(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    db_session,
    monkeypatch,
):
    from datetime import date
    from locus.config import get_settings
    from locus.models.vacation import Vacation

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    # Create autumn vacation covering Saturday 2026-10-24 through Sunday 2026-11-01
    vac = Vacation(
        name="Осенние каникулы",
        start_date=date(2026, 10, 24),
        end_date=date(2026, 11, 1),
    )
    db_session.add(vac)
    await db_session.commit()

    # Mock today as Saturday 2026-10-24
    saturday = date(2026, 10, 24)
    monkeypatch.setattr("locus.web.dashboard_routes.get_current_date", lambda: saturday)
    monkeypatch.setattr("locus.constants.get_current_date", lambda: saturday)

    # 1. Visiting / during vacation does NOT skip to Monday, stays on Saturday
    res = await client.get("/")
    assert res.status_code == 200
    assert "Суббота" in res.text
    assert "24 октября" in res.text

    # 2. Compact vacation notice is rendered
    assert "Осенние каникулы" in res.text
    assert "24.10.2026 — 01.11.2026" in res.text
    assert "уроков нет" in res.text.lower()

    # 3. Quick action for next lesson is not offered
    assert "Записать ДЗ для текущего урока" not in res.text

    # 4. Homework assigned on a vacation day is visible under "Задания на каникулы"
    from locus.models.subject import Subject
    subj = Subject(name="Литература")
    db_session.add(subj)
    await db_session.commit()
    await add_homework(
        db_session,
        test_user,
        subject_id=subj.id,
        title="Прочитать повесть на каникулах",
        due_date=saturday,
    )

    res_hw = await client.get("/")
    assert res_hw.status_code == 200
    assert "Задания на каникулы" in res_hw.text
    assert "Прочитать повесть на каникулах" in res_hw.text


@pytest.mark.asyncio
async def test_sunday_lesson_modal_shows_no_homework_notice(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    test_subject: Subject,
    db_session,
):
    """Opening modal for a Sunday lesson shows the notice and hides homework form."""
    from locus.config import get_settings
    from locus.models.lesson import Lesson

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    lesson = Lesson(
        subject_id=test_subject.id,
        day_of_week=7,
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)

    # 2026-10-25 is a Sunday
    sunday_date = "2026-10-25"
    res = await client.get(f"/dashboard/lesson/{lesson.id}/modal?date={sunday_date}")
    assert res.status_code == 200
    assert "На воскресенье домашние задания не задаются" in res.text
    assert 'modal-hw-title' not in res.text
