import pytest
from datetime import date, timedelta
from httpx import AsyncClient

from locus.models.subject import Subject


def get_valid_due_date(days_ahead: int = 1) -> str:
    d = date.today() + timedelta(days=days_ahead)
    if d.isoweekday() == 7:
        d += timedelta(days=1)
    return d.isoformat()


@pytest.mark.asyncio
async def test_homework_crud_and_status_patch(
    client: AsyncClient,
    auth_headers: dict,
    test_subject: Subject,
):
    tomorrow = get_valid_due_date(1)

    # Create HW
    res_create = await client.post(
        "/api/v1/homework",
        headers=auth_headers,
        json={
            "subject_id": test_subject.id,
            "title": "§ 12, упр. 4, 5",
            "due_date": tomorrow,
            "status": "TODO",
        },
    )
    assert res_create.status_code == 201
    hw_data = res_create.json()
    assert hw_data["title"] == "§ 12, упр. 4, 5"
    assert hw_data["status"] == "TODO"
    hw_id = hw_data["id"]

    # Patch status to DONE
    res_status = await client.patch(
        f"/api/v1/homework/{hw_id}/status",
        headers=auth_headers,
        json={"status": "DONE"},
    )
    assert res_status.status_code == 200
    assert res_status.json()["status"] == "DONE"

    # List homework filtering by status=DONE
    res_list = await client.get(
        "/api/v1/homework?status=DONE",
        headers=auth_headers,
    )
    assert res_list.status_code == 200
    items = res_list.json()
    assert any(h["id"] == hw_id for h in items)


@pytest.mark.asyncio
async def test_homework_is_shared_but_status_is_per_user(
    client: AsyncClient,
    auth_headers: dict,
    regular_auth_headers: dict,
    test_subject: Subject,
):
    tomorrow = get_valid_due_date(1)

    res_create = await client.post(
        "/api/v1/homework",
        headers=auth_headers,
        json={
            "subject_id": test_subject.id,
            "title": "Общее задание",
            "due_date": tomorrow,
        },
    )
    assert res_create.status_code == 201
    hw_id = res_create.json()["id"]

    regular_list = await client.get(
        "/api/v1/homework",
        headers=regular_auth_headers,
    )
    assert regular_list.status_code == 200
    assert any(h["id"] == hw_id for h in regular_list.json())

    regular_status = await client.patch(
        f"/api/v1/homework/{hw_id}/status",
        headers=regular_auth_headers,
        json={"status": "DONE"},
    )
    assert regular_status.status_code == 200
    assert regular_status.json()["status"] == "DONE"

    admin_status = await client.get(
        f"/api/v1/homework/{hw_id}",
        headers=auth_headers,
    )
    assert admin_status.status_code == 200
    assert admin_status.json()["status"] == "TODO"


@pytest.mark.asyncio
async def test_homework_invalid_lesson_id_rejected(
    client: AsyncClient,
    auth_headers: dict,
    test_subject: Subject,
):
    """Providing a non-existent or foreign lesson_id must return 404."""
    tomorrow = get_valid_due_date(1)
    res = await client.post(
        "/api/v1/homework",
        headers=auth_headers,
        json={
            "subject_id": test_subject.id,
            "lesson_id": 999999,
            "title": "Задание с неверным уроком",
            "due_date": tomorrow,
        },
    )
    assert res.status_code == 404
    assert "урок не найден" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_homework_web_toggle(
    client: AsyncClient,
    auth_token: str,
    test_subject: Subject,
):
    """Test HTMX toggle endpoint in web UI."""
    from locus.config import get_settings
    settings = get_settings()
    client.cookies.set(settings.COOKIE_NAME, auth_token)

    tomorrow = get_valid_due_date(1)

    # Create HW via web
    res_create = await client.post(
        "/homework",
        data={
            "subject_id": test_subject.id,
            "title": "Сочинение по литературе",
            "due_date": tomorrow,
        },
        follow_redirects=False,
    )
    assert res_create.status_code == 303

    # Check that homework is in list
    res_list = await client.get("/homework")
    assert res_list.status_code == 200
    assert "Сочинение по литературе" in res_list.text

    # Extract ID and toggle status via HTMX endpoint
    res_api = await client.get("/api/v1/homework")
    hw_id = res_api.json()[0]["id"]

    # Toggle to DONE (default full card view)
    res_toggle = await client.post(f"/homework/{hw_id}/toggle")
    assert res_toggle.status_code == 200
    assert "hw-done-title" in res_toggle.text

    # Toggle back to TODO with compact view (diary view)
    res_toggle_compact = await client.post(f"/homework/{hw_id}/toggle?view=compact")
    assert res_toggle_compact.status_code == 200
    assert "hw-done-title" not in res_toggle_compact.text
    assert f'id="hw-card-{hw_id}"' in res_toggle_compact.text

    # Toggle to DONE with unassigned view
    res_toggle_unassigned = await client.post(f"/homework/{hw_id}/toggle?view=unassigned")
    assert res_toggle_unassigned.status_code == 200
    assert "hw-done-title" in res_toggle_unassigned.text
    assert f'id="unassigned-hw-{hw_id}"' in res_toggle_unassigned.text


@pytest.mark.asyncio
async def test_set_status_concurrency_resilience(
    db_session,
    test_user,
    test_subject: Subject,
):
    """Test set_status correctly updates status idempotently."""
    from datetime import date
    from locus.homework_status import get_completion, set_status
    from locus.models.homework import Homework

    hw = Homework(
        subject_id=test_subject.id,
        title="Тест гонки",
        due_date=date(2026, 10, 25),
    )
    db_session.add(hw)
    await db_session.commit()
    await db_session.refresh(hw)

    # First call creates completion
    c1 = await set_status(db_session, hw.id, test_user.id, "DONE")
    await db_session.commit()
    assert c1.status == "DONE"

    # Second call updates completion
    c2 = await set_status(db_session, hw.id, test_user.id, "TODO")
    await db_session.commit()
    assert c2.status == "TODO"

    final = await get_completion(db_session, hw.id, test_user.id)
    assert final.status == "TODO"


@pytest.mark.asyncio
async def test_api_todo_filter_includes_uncompleted_and_excludes_done(
    client: AsyncClient,
    auth_headers: dict,
    test_subject: Subject,
):
    """REST API ?status=TODO returns tasks without completion records and excludes DONE tasks."""
    tomorrow = get_valid_due_date(1)

    # Create task 1 (will stay uncompleted / default TODO)
    r1 = await client.post(
        "/api/v1/homework",
        headers=auth_headers,
        json={"subject_id": test_subject.id, "title": "Задача без completion", "due_date": tomorrow},
    )
    hw1_id = r1.json()["id"]

    # Create task 2 and mark it DONE
    r2 = await client.post(
        "/api/v1/homework",
        headers=auth_headers,
        json={"subject_id": test_subject.id, "title": "Задача выполненная", "due_date": tomorrow},
    )
    hw2_id = r2.json()["id"]
    await client.patch(
        f"/api/v1/homework/{hw2_id}/status",
        headers=auth_headers,
        json={"status": "DONE"},
    )

    # Filter ?status=TODO
    r_todo = await client.get("/api/v1/homework?status=TODO", headers=auth_headers)
    assert r_todo.status_code == 200
    ids_todo = [h["id"] for h in r_todo.json()]
    assert hw1_id in ids_todo
    assert hw2_id not in ids_todo


@pytest.mark.asyncio
async def test_homework_cannot_be_assigned_on_sunday(
    client: AsyncClient,
    auth_headers: dict,
    auth_token: str,
    test_subject: Subject,
    db_session,
):
    """Ensure homework cannot be assigned on Sunday via API and Web."""
    from locus.config import get_settings
    from locus.models.lesson import Lesson
    settings = get_settings()

    # Find next Sunday
    today = date.today()
    days_until_sunday = (7 - today.isoweekday()) % 7
    if days_until_sunday == 0:
        sunday = today
    else:
        sunday = today + timedelta(days=days_until_sunday)
    sunday_str = sunday.isoformat()

    # 1. API creation must fail with 422
    res_api = await client.post(
        "/api/v1/homework",
        headers=auth_headers,
        json={
            "subject_id": test_subject.id,
            "title": "Домашка на воскресенье",
            "due_date": sunday_str,
        },
    )
    assert res_api.status_code == 422
    assert "Нельзя записать домашнее задание на воскресенье" in res_api.text

    # 2. Web creation must fail with 400
    client.cookies.set(settings.COOKIE_NAME, auth_token)
    res_web = await client.post(
        "/homework",
        data={
            "subject_id": test_subject.id,
            "title": "Домашка на воскресенье через веб",
            "due_date": sunday_str,
        },
        follow_redirects=False,
    )
    assert res_web.status_code == 400
    assert "Нельзя записать домашнее задание на воскресенье" in res_web.text

    # 3. Lesson modal homework creation must fail with 400
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

    res_modal = await client.post(
        f"/dashboard/lesson/{lesson.id}/homework?date={sunday_str}",
        data={"title": "Домашка на воскресенье из модалки"},
    )
    assert res_modal.status_code == 400
    assert "Нельзя записать домашнее задание на воскресенье" in res_modal.text
