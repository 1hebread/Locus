import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.models.lesson import Lesson
from locus.models.subject import Subject
from locus.models.user import User
from tests.helpers import add_homework, next_valid_due_date


@pytest.mark.asyncio
async def test_pwa_manifest_and_static(client: AsyncClient):
    """Test PWA manifest is served correctly with standalone display."""
    res = await client.get("/static/manifest.json")
    assert res.status_code == 200
    data = res.json()
    assert data["display"] == "standalone"
    assert data["short_name"] == "Locus"
    assert len(data["icons"]) >= 2

    # Root service worker delivery with scope header
    sw_res = await client.get("/sw.js")
    assert sw_res.status_code == 200
    assert sw_res.headers.get("Service-Worker-Allowed") == "/"
    assert "application/javascript" in sw_res.headers.get("Content-Type", "")


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
async def test_dashboard_copy_homework_text(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    test_subject: Subject,
    db_session,
):
    """Each day with homework exposes its tasks in the copy-to-clipboard format."""
    from datetime import date

    from locus.config import get_settings

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    target = date(2026, 10, 26)  # Monday
    lesson = Lesson(
        subject_id=test_subject.id,
        day_of_week=1,
        lesson_number=1,
        start_time="08:00",
        end_time="08:45",
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)
    await add_homework(
        db_session,
        test_user,
        subject_id=test_subject.id,
        lesson_id=lesson.id,
        title="Решить 3 уравнения с котами",
        due_date=target,
    )
    await add_homework(
        db_session,
        test_user,
        subject_id=test_subject.id,
        title="Дополнительное задание",
        due_date=target,
    )

    res = await client.get(f"/?date={target.isoformat()}")
    assert res.status_code == 200
    assert 'data-copy-scope="#desktop-day-pane-2026-10-26"' in res.text
    assert 'data-copy-scope="#mobile-day-1"' in res.text
    assert 'data-copy-line="Алгебра: Решить 3 уравнения с котами"' in res.text
    assert 'data-copy-line="Алгебра: Дополнительное задание"' in res.text


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

    fixed_now = datetime(2026, 10, 22, 9, 0, tzinfo=ZoneInfo("Asia/Almaty"))
    today = fixed_now.date()
    monkeypatch.setattr(
        "locus.web.dashboard_routes.get_current_date",
        lambda: today,
    )
    monkeypatch.setattr(
        "locus.web.dashboard_routes.get_current_datetime",
        lambda: fixed_now,
    )

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

    # The quick-action button must be visible (must not have the 'hidden' utility class)
    import re
    btn_match = re.search(r'<button[^>]*data-next-lesson-btn[^>]*class="([^"]*)"', res.text)
    assert btn_match is not None
    assert "hidden" not in btn_match.group(1).split()


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
async def test_lesson_modal_next_lesson_button_and_saving(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    test_subject: Subject,
    db_session,
):
    """Option B: lesson modal displays 'На след. урок' button targeting next subject date."""
    from datetime import date
    from sqlalchemy import select
    from locus.config import get_settings
    from locus.models.homework import Homework
    from locus.models.lesson import Lesson

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    # Lesson 1 on Monday (day 1), Lesson 2 on Thursday (day 4)
    lesson1 = Lesson(
        subject_id=test_subject.id,
        day_of_week=1,
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
    )
    lesson2 = Lesson(
        subject_id=test_subject.id,
        day_of_week=4,
        lesson_number=2,
        start_time="09:25",
        end_time="10:10",
    )
    db_session.add_all([lesson1, lesson2])
    await db_session.commit()
    await db_session.refresh(lesson1)
    await db_session.refresh(lesson2)

    mon_date = "2026-10-19"  # Monday
    thu_date = "2026-10-22"  # Thursday

    # Open modal for Monday lesson
    res_modal = await client.get(f"/dashboard/lesson/{lesson1.id}/modal?date={mon_date}")
    assert res_modal.status_code == 200
    assert "След. урок (Чт, 22 окт)" in res_modal.text
    assert f'hx-post="/dashboard/lesson/{lesson2.id}/homework?date={thu_date}&forward=true"' in res_modal.text
    assert 'hx-params="title"' in res_modal.text
    assert 'type="button"' in res_modal.text
    assert 'hx-disabled-elt="closest form find button"' in res_modal.text

    # Save homework directly to the next lesson via that endpoint
    res_save = await client.post(
        f"/dashboard/lesson/{lesson2.id}/homework?date={thu_date}&forward=true",
        data={
            "title": "Упр. 42 на четверг",
        },
    )
    assert res_save.status_code == 200
    assert f'id="m-lesson-card-{lesson2.id}-4"' in res_save.text
    assert "closeModal('lesson-detail-modal')" in res_save.text

    # Verify homework in DB and that its status is TODO
    from locus.constants import HomeworkStatus
    from locus.homework_status import get_completion, set_status

    thu_hw_res = await db_session.execute(
        select(Homework).where(
            Homework.lesson_id == lesson2.id,
            Homework.due_date == date.fromisoformat(thu_date),
        )
    )
    thu_hw = thu_hw_res.scalar_one_or_none()
    assert thu_hw is not None
    assert thu_hw.title == "Упр. 42 на четверг"
    completion = await get_completion(db_session, thu_hw.id, test_user.id)
    assert completion is not None
    assert completion.status == HomeworkStatus.TODO.value

    # Mark Thursday homework as DONE
    await set_status(db_session, thu_hw.id, test_user.id, HomeworkStatus.DONE.value)

    # Verify Monday has no homework created
    mon_hw_res = await db_session.execute(
        select(Homework).where(
            Homework.lesson_id == lesson1.id,
            Homework.due_date == date.fromisoformat(mon_date),
        )
    )
    assert mon_hw_res.scalar_one_or_none() is None

    # Cross-date safety test: create homework on Monday
    mon_hw = Homework(
        subject_id=test_subject.id,
        lesson_id=lesson1.id,
        title="Упр. 10 для понедельника",
        due_date=date.fromisoformat(mon_date),
    )
    db_session.add(mon_hw)
    await db_session.commit()
    await db_session.refresh(mon_hw)

    # Submitting with mon_hw.id and forward=true to Thursday must NOT modify or reassign Monday's homework
    # and must preserve Thursday's existing DONE status
    res_save_again = await client.post(
        f"/dashboard/lesson/{lesson2.id}/homework?date={thu_date}&forward=true",
        data={
            "hw_id": mon_hw.id,
            "title": "Упр. 42 (обновлено) на четверг",
        },
    )
    assert res_save_again.status_code == 200

    # Reload Monday homework: must be completely untouched
    await db_session.refresh(mon_hw)
    assert mon_hw.title == "Упр. 10 для понедельника"
    assert mon_hw.lesson_id == lesson1.id
    assert mon_hw.due_date == date.fromisoformat(mon_date)

    # Thursday homework updated, but completion status is preserved as DONE
    await db_session.refresh(thu_hw)
    assert thu_hw.title == "Упр. 42 (обновлено) на четверг"
    thu_completion = await get_completion(db_session, thu_hw.id, test_user.id)
    assert thu_completion.status == HomeworkStatus.DONE.value


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
    from sqlalchemy import select
    from locus.config import get_settings
    from locus.models.homework import Homework

    settings = get_settings()
    tomorrow = next_valid_due_date(1).isoformat()

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
async def test_dashboard_vacation_banner_and_weekend_advances_to_monday(
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

    # 1. Visiting / during vacation on weekend advances to Monday (2026-10-26)
    res = await client.get("/")
    assert res.status_code == 200
    assert "Понедельник" in res.text
    assert "26 октября" in res.text

    # 2. Compact vacation notice is rendered on Monday
    assert "Осенние каникулы" in res.text
    assert "24.10.2026 — 01.11.2026" in res.text
    assert "уроков нет" in res.text.lower()

    # 3. Quick action for next lesson is not offered
    assert "Записать ДЗ для текущего урока" not in res.text

    # 4. Explicitly visiting Saturday shows homework under "Задания на каникулы"
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

    res_hw = await client.get("/?date=2026-10-24")
    assert res_hw.status_code == 200
    assert "Суббота" in res_hw.text
    assert "24 октября" in res_hw.text
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


@pytest.mark.asyncio
async def test_lesson_web_admin_creation_and_conflict_validation(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    test_subject: Subject,
    db_session,
):
    from locus.config import get_settings
    from locus.models.lesson import Lesson
    from sqlalchemy import select

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    # 1. Admin creates valid lesson 1 on Monday via web
    res_create = await client.post(
        "/schedule",
        data={
            "subject_id": test_subject.id,
            "day_of_week": 1,
            "lesson_number": 1,
            "start_time": "08:00",
            "end_time": "08:45",
            "room": "101",
        },
        follow_redirects=False,
    )
    assert res_create.status_code == 303
    assert res_create.headers["Location"] == "/schedule"

    # Verify lesson exists in DB
    lesson_res = await db_session.execute(
        select(Lesson).where(Lesson.day_of_week == 1, Lesson.lesson_number == 1)
    )
    lesson = lesson_res.scalars().first()
    assert lesson is not None
    assert lesson.room == "101"

    # 2. Duplicate lesson 1 on Monday rejected with 400
    res_dup = await client.post(
        "/schedule",
        data={
            "subject_id": test_subject.id,
            "day_of_week": 1,
            "lesson_number": 1,
            "start_time": "09:00",
            "end_time": "09:45",
        },
        follow_redirects=False,
    )
    assert res_dup.status_code == 400
    assert "Урок №1 в этот день уже существует" in res_dup.json()["detail"]

    # 3. Overlapping time on Monday rejected with 400
    res_overlap = await client.post(
        "/schedule",
        data={
            "subject_id": test_subject.id,
            "day_of_week": 1,
            "lesson_number": 2,
            "start_time": "08:30",
            "end_time": "09:15",
        },
        follow_redirects=False,
    )
    assert res_overlap.status_code == 400
    assert "пересекается с уроком №1" in res_overlap.json()["detail"]

    # 4. Invalid time order (start >= end) rejected with 400
    res_invalid_time = await client.post(
        "/schedule",
        data={
            "subject_id": test_subject.id,
            "day_of_week": 1,
            "lesson_number": 2,
            "start_time": "09:30",
            "end_time": "09:00",
        },
        follow_redirects=False,
    )
    assert res_invalid_time.status_code == 400
    assert "Время окончания урока должно быть позже времени начала" in res_invalid_time.json()["detail"]

    # 5. Invalid day_of_week or lesson_number rejected with 400
    res_bad_day = await client.post(
        "/schedule",
        data={
            "subject_id": test_subject.id,
            "day_of_week": 8,
            "lesson_number": 1,
            "start_time": "08:00",
            "end_time": "08:45",
        },
        follow_redirects=False,
    )
    assert res_bad_day.status_code == 400

    res_sunday = await client.post(
        "/schedule",
        data={
            "subject_id": test_subject.id,
            "day_of_week": 7,
            "lesson_number": 1,
            "start_time": "08:00",
            "end_time": "08:45",
        },
        follow_redirects=False,
    )
    assert res_sunday.status_code == 400
    assert "День недели должен быть от 1 до 6" in res_sunday.json()["detail"]

    # 6. Schedule page contains schedule_data JSON
    res_page = await client.get("/schedule")
    assert res_page.status_code == 200
    assert "scheduleDataByDay" in res_page.text

    # 7. Safe truncation of room (>50) and note (>255)
    long_room = "R" * 80
    long_note = "N" * 300
    res_trunc = await client.post(
        "/schedule",
        data={
            "subject_id": test_subject.id,
            "day_of_week": 2,
            "lesson_number": 1,
            "start_time": "08:00",
            "end_time": "08:45",
            "room": long_room,
            "note": long_note,
        },
        headers={"Accept": "application/json"},
    )
    assert res_trunc.status_code == 200
    assert res_trunc.json()["ok"] is True
    assert res_trunc.json()["redirect"] == "/schedule"
    assert "2" in res_trunc.json()["days"]
    assert res_trunc.json()["days"]["2"]["count"] == 1
    assert "lesson-card-" in res_trunc.json()["days"]["2"]["html"]

    # Verify truncated values in DB
    lesson2_res = await db_session.execute(
        select(Lesson).where(Lesson.day_of_week == 2, Lesson.lesson_number == 1)
    )
    lesson2 = lesson2_res.scalars().first()
    assert lesson2 is not None
    assert len(lesson2.room) == 50
    assert len(lesson2.note) == 255


@pytest.mark.asyncio
async def test_lesson_web_admin_edit_settings_and_conflict_validation(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    test_subject: Subject,
    db_session,
):
    from datetime import date
    from locus.config import get_settings
    from locus.models.homework import Homework
    from locus.models.lesson import Lesson
    from locus.models.user import User
    from locus.security import create_access_token, get_password_fingerprint, hash_password
    from sqlalchemy import select

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    # 1. Create a lesson and another subject
    subj2 = Subject(name="География")
    db_session.add(subj2)
    await db_session.commit()
    await db_session.refresh(subj2)

    lesson1 = Lesson(
        subject_id=test_subject.id,
        day_of_week=3,
        lesson_number=2,
        start_time="09:00",
        end_time="09:45",
        week_type="ALL",
        room="101",
        note="Заметка 1",
    )
    lesson2 = Lesson(
        subject_id=test_subject.id,
        day_of_week=3,
        lesson_number=3,
        start_time="10:00",
        end_time="10:45",
        week_type="ALL",
        subgroup=1,
    )
    db_session.add_all([lesson1, lesson2])
    await db_session.commit()
    await db_session.refresh(lesson1)
    await db_session.refresh(lesson2)

    # Link a homework assignment to lesson1
    hw = Homework(
        subject_id=test_subject.id,
        lesson_id=lesson1.id,
        title="Тест ДЗ",
        due_date=date(2026, 11, 4),
        subgroup=None,
    )
    db_session.add(hw)
    await db_session.commit()

    # 2. GET fallback redirects to /schedule
    res_get = await client.get(f"/schedule/{lesson1.id}/edit", follow_redirects=False)
    assert res_get.status_code == 303
    assert res_get.headers["Location"] == "/schedule"

    # 3. Admin edits lesson settings (changes subject, room, note, subgroup to 1)
    res_edit = await client.post(
        f"/schedule/{lesson1.id}/edit",
        data={
            "subject_id": subj2.id,
            "day_of_week": 3,
            "lesson_number": 2,
            "start_time": "08:55",
            "end_time": "09:40",
            "subgroup": 1,
            "room": "205",
            "note": "Обновленная заметка",
        },
        headers={"Accept": "application/json"},
    )
    assert res_edit.status_code == 200
    assert res_edit.json()["ok"] is True
    assert "3" in res_edit.json()["days"]
    assert res_edit.json()["days"]["3"]["count"] == 2

    # Verify changes in DB
    await db_session.refresh(lesson1)
    assert lesson1.subject_id == subj2.id
    assert lesson1.start_time == "08:55"
    assert lesson1.end_time == "09:40"
    assert str(lesson1.subgroup) == "1"
    assert lesson1.room == "205"
    assert lesson1.note == "Обновленная заметка"

    # Verify linked homework was unbound from the lesson because subject changed
    await db_session.refresh(hw)
    assert hw.lesson_id is None
    assert hw.subject_id == test_subject.id

    # Create a homework for subj2 linked to lesson1
    hw2 = Homework(
        subject_id=subj2.id,
        lesson_id=lesson1.id,
        title="Тест ДЗ по географии",
        due_date=date(2026, 11, 4),
        subgroup=1,
    )
    db_session.add(hw2)
    await db_session.commit()

    # Edit lesson1 subgroup to 2 (without changing subject or day)
    res_edit_sub = await client.post(
        f"/schedule/{lesson1.id}/edit",
        data={
            "subject_id": subj2.id,
            "day_of_week": 3,
            "lesson_number": 2,
            "start_time": "08:55",
            "end_time": "09:40",
            "subgroup": 2,
            "room": "205",
        },
        headers={"Accept": "application/json"},
    )
    assert res_edit_sub.status_code == 200

    # Verify hw2 remained attached and synced its subgroup
    await db_session.refresh(hw2)
    assert hw2.lesson_id == lesson1.id
    assert str(hw2.subgroup) == "2"

    # 4. Conflict: trying to edit lesson1 to conflict with lesson2 (lesson_number=3, subgroup=1)
    res_conflict = await client.post(
        f"/schedule/{lesson1.id}/edit",
        data={
            "subject_id": subj2.id,
            "day_of_week": 3,
            "lesson_number": 3,
            "start_time": "10:00",
            "end_time": "10:45",
            "subgroup": 1,
        },
    )
    assert res_conflict.status_code == 400
    assert "Урок №3" in res_conflict.json()["detail"] and "уже существует" in res_conflict.json()["detail"]

    # 5. Non-admin cannot edit lesson (403 Forbidden)
    reg_user = User(
        username="student_regular",
        hashed_password=hash_password("pass123"),
        is_active=True,
        is_admin=False,
    )
    db_session.add(reg_user)
    await db_session.commit()
    await db_session.refresh(reg_user)
    t_reg = create_access_token({"sub": str(reg_user.id), "pwd": get_password_fingerprint(reg_user.hashed_password)})

    client.cookies.set(settings.COOKIE_NAME, t_reg)
    res_forbidden = await client.post(
        f"/schedule/{lesson1.id}/edit",
        data={
            "subject_id": subj2.id,
            "day_of_week": 3,
            "lesson_number": 2,
            "start_time": "08:55",
            "end_time": "09:40",
        },
    )
    assert res_forbidden.status_code == 403

    # 6. Verify schedule page renders edit button and modal for admin
    client.cookies.set(settings.COOKIE_NAME, auth_token)
    res_page = await client.get("/schedule")
    assert res_page.status_code == 200
    assert f'id="btn-edit-lesson-{lesson1.id}"' in res_page.text
    assert 'id="edit-lesson-modal"' in res_page.text
    assert "Настройки урока" in res_page.text
    assert 'id="day-counter-3"' in res_page.text
    assert 'id="day-lessons-3"' in res_page.text
    assert "updateDayLessonsUI" in res_page.text

    # 7. Test moving lesson1 across days: day 3 -> day 4
    res_move = await client.post(
        f"/schedule/{lesson1.id}/edit",
        data={
            "subject_id": subj2.id,
            "day_of_week": 4,
            "lesson_number": 2,
            "start_time": "08:55",
            "end_time": "09:40",
            "subgroup": 2,
            "room": "205",
        },
        headers={"Accept": "application/json"},
    )
    assert res_move.status_code == 200
    assert "3" in res_move.json()["days"]
    assert "4" in res_move.json()["days"]
    assert res_move.json()["days"]["3"]["count"] == 1  # Only lesson2 remains on day 3
    assert res_move.json()["days"]["4"]["count"] == 1  # lesson1 is now on day 4

    # Verify hw2 (which was on lesson1) is unlinked because day changed
    await db_session.refresh(hw2)
    assert hw2.lesson_id is None

    # Move lesson1 back to day 3 without Accept: application/json (tests 303 Redirect fallback)
    res_fallback = await client.post(
        f"/schedule/{lesson1.id}/edit",
        data={
            "subject_id": subj2.id,
            "day_of_week": 3,
            "lesson_number": 2,
            "start_time": "08:55",
            "end_time": "09:40",
            "subgroup": 2,
            "room": "205",
        },
        follow_redirects=False,
    )
    assert res_fallback.status_code == 303
    assert res_fallback.headers["Location"] == "/schedule"

    # Test invalid day_of_week=7 (Sunday) on edit rejected with 400
    res_edit_sunday = await client.post(
        f"/schedule/{lesson1.id}/edit",
        data={
            "subject_id": subj2.id,
            "day_of_week": 7,
            "lesson_number": 2,
            "start_time": "08:55",
            "end_time": "09:40",
        },
    )
    assert res_edit_sunday.status_code == 400
    assert "День недели должен быть от 1 до 6" in res_edit_sunday.json()["detail"]

    # Test editing non-existent lesson returns 404
    res_edit_404 = await client.post(
        "/schedule/999999/edit",
        data={
            "subject_id": subj2.id,
            "day_of_week": 3,
            "lesson_number": 2,
            "start_time": "08:55",
            "end_time": "09:40",
        },
    )
    assert res_edit_404.status_code == 404

    # Test deleting non-existent lesson returns 404
    res_del_404 = await client.delete("/schedule/999999")
    assert res_del_404.status_code == 404

    # 8. Admin deletes lesson via JSON DELETE endpoint (used by modal delete)
    res_del_json = await client.delete(
        f"/schedule/{lesson1.id}",
        headers={"Accept": "application/json"},
    )
    assert res_del_json.status_code == 200
    assert res_del_json.json()["ok"] is True
    assert "3" in res_del_json.json()["days"]
    assert res_del_json.json()["days"]["3"]["count"] == 1
    assert (await db_session.get(Lesson, lesson1.id)) is None

    # 9. Admin deletes lesson2 via HTMX DELETE endpoint (used by card cross button)
    res_del_htmx = await client.delete(f"/schedule/{lesson2.id}")
    assert res_del_htmx.status_code == 200
    assert res_del_htmx.text == ""
    assert (await db_session.get(Lesson, lesson2.id)) is None


@pytest.mark.asyncio
async def test_desktop_multi_day_panes_rendering(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    test_subject: Subject,
    db_session,
    monkeypatch,
):
    from datetime import date
    from locus.config import get_settings
    from locus.models.lesson import Lesson

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    # Monday 2026-10-19
    fixed_date = date(2026, 10, 19)
    monkeypatch.setattr("locus.web.dashboard_routes.get_current_date", lambda: fixed_date)
    monkeypatch.setattr("locus.constants.get_current_date", lambda: fixed_date)

    # Lesson on Monday (day 1)
    lesson_mon = Lesson(
        subject_id=test_subject.id,
        day_of_week=1,
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
    )
    # Lesson on Tuesday (day 2)
    lesson_tue = Lesson(
        subject_id=test_subject.id,
        day_of_week=2,
        lesson_number=1,
        start_time="08:30",
        end_time="09:15",
    )
    db_session.add_all([lesson_mon, lesson_tue])
    await db_session.commit()

    # Request dashboard for Monday
    res = await client.get("/?date=2026-10-19")
    assert res.status_code == 200

    # Verify both day panes exist in the DOM
    assert 'id="desktop-day-pane-2026-10-19"' in res.text
    assert 'id="desktop-day-pane-2026-10-20"' in res.text

    # Monday should NOT be hidden (is_selected is True)
    assert 'id="desktop-day-pane-2026-10-19"' in res.text
    assert 'desktop-day-pane space-y-6 ' in res.text

    # Tuesday should be hidden (is_selected is False)
    assert 'id="desktop-day-pane-2026-10-20"' in res.text
    assert 'hidden' in res.text

    # Both lessons are rendered in the HTML
    assert f'id="lesson-card-{lesson_mon.id}"' in res.text
    assert f'id="lesson-card-{lesson_tue.id}"' in res.text

    # Tuesday lesson card has target date 2026-10-20 in its modal url
    assert f'hx-get="/dashboard/lesson/{lesson_tue.id}/modal?date=2026-10-20"' in res.text
    # Monday lesson card has target date 2026-10-19 in its modal url
    assert f'hx-get="/dashboard/lesson/{lesson_mon.id}/modal?date=2026-10-19"' in res.text

    # Tabs have data-day-tab attributes
    assert 'data-day-tab="2026-10-19"' in res.text
    assert 'data-day-tab="2026-10-20"' in res.text

    # Default subgroup attribute is present
    assert 'data-current-subgroup="all"' in res.text

    # Request dashboard with specific subgroup
    res_sub = await client.get("/?date=2026-10-19&subgroup=1")
    assert res_sub.status_code == 200
    assert 'data-current-subgroup="1"' in res_sub.text


@pytest.mark.asyncio
async def test_clone_lesson_web(
    client: AsyncClient,
    auth_cookies: dict,
    test_subject: Subject,
    db_session: AsyncSession,
):
    """Test web endpoint for cloning lesson with opposite subgroup."""
    for k, v in auth_cookies.items():
        client.cookies.set(k, v)

    subj_id = test_subject.id

    # 1. Create a lesson for subgroup 2 on Friday
    lesson = Lesson(
        subject_id=subj_id,
        day_of_week=5,
        lesson_number=3,
        start_time="09:40",
        end_time="10:25",
        subgroup=2,
        room="305",
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)

    # 2. Clone it via web POST
    res_clone = await client.post(
        f"/schedule/{lesson.id}/clone",
        headers={"Accept": "application/json"},
    )
    assert res_clone.status_code == 200
    data = res_clone.json()
    assert data["ok"] is True
    assert "5" in data["days"]
    assert data["days"]["5"]["count"] == 2

    # Verify both lessons in DB
    lessons_res = await db_session.execute(
        select(Lesson).where(Lesson.day_of_week == 5, Lesson.lesson_number == 3)
    )
    all_lessons = list(lessons_res.scalars().all())
    assert len(all_lessons) == 2
    subgroups = {str(l.subgroup) for l in all_lessons}
    assert subgroups == {"1", "2"}

    # Verify target room was set from subject.room ("304")
    sub1_lesson = next(l for l in all_lessons if str(l.subgroup) == "1")
    assert sub1_lesson.room == "304"

    # With both subgroups present, clone buttons must be hidden in the rendered HTML
    day_html = data["days"]["5"]["html"]
    for l in all_lessons:
        assert f"btn-clone-lesson-{l.id}" not in day_html

    # Verify clone button is removed from edit modal
    res_page = await client.get("/schedule")
    assert res_page.status_code == 200
    assert 'id="edit-lesson-clone-btn"' not in res_page.text


@pytest.mark.asyncio
async def test_vacation_spanning_weekend_does_not_show_weekend_tabs(
    client: AsyncClient,
    test_user: User,
    auth_token: str,
    test_subject: Subject,
    db_session,
    monkeypatch,
):
    """Vacations covering Saturday and Sunday should not force weekend tabs/panes on desktop."""
    from datetime import date
    from locus.config import get_settings
    from locus.models.lesson import Lesson
    from locus.models.vacation import Vacation

    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    # Vacation covering Monday 2026-10-26 through Sunday 2026-11-01
    vac = Vacation(
        name="Осенние каникулы",
        start_date=date(2026, 10, 26),
        end_date=date(2026, 11, 1),
    )
    db_session.add(vac)
    await db_session.commit()

    monday = date(2026, 10, 26)
    monkeypatch.setattr("locus.web.dashboard_routes.get_current_date", lambda: monday)
    monkeypatch.setattr("locus.constants.get_current_date", lambda: monday)

    res = await client.get("/?date=2026-10-26")
    assert res.status_code == 200

    # Weekday panes exist
    assert 'data-day-tab="2026-10-26"' in res.text
    assert 'data-day-tab="2026-10-30"' in res.text
    assert 'id="desktop-day-pane-2026-10-26"' in res.text
    assert 'id="desktop-day-pane-2026-10-30"' in res.text

    # Weekend panes/tabs must NOT appear simply due to vacation
    assert 'data-day-tab="2026-10-31"' not in res.text
    assert 'data-day-tab="2026-11-01"' not in res.text
    assert 'id="desktop-day-pane-2026-10-31"' not in res.text
    assert 'id="desktop-day-pane-2026-11-01"' not in res.text

    # But if explicitly selected (?date=2026-10-31), Saturday appears
    res_sat = await client.get("/?date=2026-10-31")
    assert res_sat.status_code == 200
    assert 'data-day-tab="2026-10-31"' in res_sat.text
    assert 'id="desktop-day-pane-2026-10-31"' in res_sat.text
    # Sunday is still not selected and must not appear
    assert 'data-day-tab="2026-11-01"' not in res_sat.text
    assert 'id="desktop-day-pane-2026-11-01"' not in res_sat.text

    # If Sunday has a scheduled lesson, it should appear
    sunday_lesson = Lesson(
        subject_id=test_subject.id,
        day_of_week=7,
        lesson_number=1,
        start_time="10:00",
        end_time="10:45",
    )
    db_session.add(sunday_lesson)
    await db_session.commit()

    res_with_lesson = await client.get("/?date=2026-10-26")
    assert res_with_lesson.status_code == 200
    assert 'data-day-tab="2026-11-01"' in res_with_lesson.text
    assert 'id="desktop-day-pane-2026-11-01"' in res_with_lesson.text
