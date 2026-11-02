from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.homework_audit import (
    ACTION_CREATED,
    ACTION_UPDATED,
    log_homework_event,
    snapshot_changes,
)
from locus.models.homework import Homework
from locus.models.homework_event import HomeworkEvent
from locus.models.lesson import Lesson
from locus.models.subject import Subject
from locus.models.user import User


async def _events(db_session: AsyncSession) -> list[HomeworkEvent]:
    result = await db_session.execute(
        select(HomeworkEvent).order_by(HomeworkEvent.id)
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_api_content_changes_are_logged(
    client: AsyncClient,
    db_session: AsyncSession,
    test_subject: Subject,
    auth_headers: dict,
):
    payload = {
        "subject_id": test_subject.id,
        "title": "Старое ДЗ",
        "due_date": "2026-11-02",
    }
    created = await client.post(
        "/api/v1/homework", json=payload, headers=auth_headers
    )
    assert created.status_code == 201
    hw_id = created.json()["id"]

    events = await _events(db_session)
    assert [event.action for event in events] == ["created"]
    assert events[0].actor_username == "student"
    assert events[0].actor_key_name is None
    assert events[0].changes["title"] == [None, "Старое ДЗ"]

    # Personal status toggles are not content edits and must not be logged
    toggled = await client.patch(
        f"/api/v1/homework/{hw_id}/status",
        json={"status": "DONE"},
        headers=auth_headers,
    )
    assert toggled.status_code == 200
    assert await db_session.scalar(select(func.count(HomeworkEvent.id))) == 1

    updated = await client.put(
        f"/api/v1/homework/{hw_id}",
        json={"title": "Новое ДЗ"},
        headers=auth_headers,
    )
    assert updated.status_code == 200

    events = await _events(db_session)
    assert events[-1].action == "updated"
    assert events[-1].changes["title"] == ["Старое ДЗ", "Новое ДЗ"]
    assert events[-1].changes["subject_id"] == [test_subject.id, test_subject.id]
    assert events[-1].changes["due_date"] == ["2026-11-02", "2026-11-02"]

    deleted = await client.delete(f"/api/v1/homework/{hw_id}", headers=auth_headers)
    assert deleted.status_code == 204

    events = await _events(db_session)
    assert events[-1].action == "deleted"
    assert events[-1].homework_id is None
    assert events[-1].changes["title"] == ["Новое ДЗ", None]


@pytest.mark.asyncio
async def test_web_create_and_delete_are_logged(
    client: AsyncClient,
    db_session: AsyncSession,
    test_subject: Subject,
    auth_headers: dict,
):
    created = await client.post(
        "/homework",
        data={
            "subject_id": test_subject.id,
            "title": "Из веба",
            "due_date": "2026-11-02",
        },
        headers=auth_headers,
    )
    assert created.status_code == 303

    hw = (await db_session.execute(select(Homework))).scalar_one()
    events = await _events(db_session)
    assert events[-1].action == "created"
    assert events[-1].homework_id == hw.id

    removed = await client.delete(f"/homework/{hw.id}", headers=auth_headers)
    assert removed.status_code == 200

    events = await _events(db_session)
    assert events[-1].action == "deleted"
    assert events[-1].changes["title"] == ["Из веба", None]


@pytest.mark.asyncio
async def test_lesson_modal_shows_last_editor(
    client: AsyncClient,
    db_session: AsyncSession,
    test_subject: Subject,
    test_user: User,
    auth_headers: dict,
):
    lesson = Lesson(
        subject_id=test_subject.id,
        day_of_week=1,
        lesson_number=1,
        start_time="08:00",
        end_time="08:45",
        week_type="ALL",
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)

    target_date = "2026-10-26"
    hw = Homework(
        subject_id=test_subject.id,
        lesson_id=lesson.id,
        title="ДЗ к уроку",
        due_date=date.fromisoformat(target_date),
    )
    db_session.add(hw)
    await db_session.commit()
    await db_session.refresh(hw)

    log_homework_event(
        db_session, test_user, ACTION_CREATED, hw.id, snapshot_changes(hw)
    )
    await db_session.commit()

    response = await client.get(
        f"/dashboard/lesson/{lesson.id}/modal?date={target_date}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert "Изменил: student" in response.text


@pytest.mark.asyncio
async def test_admin_history_page(
    client: AsyncClient,
    db_session: AsyncSession,
    test_subject: Subject,
    test_user: User,
    auth_headers: dict,
    regular_auth_headers: dict,
):
    lesson = Lesson(
        subject_id=test_subject.id,
        day_of_week=1,
        lesson_number=1,
        start_time="08:00",
        end_time="08:45",
        week_type="ALL",
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)

    hw = Homework(
        subject_id=test_subject.id,
        lesson_id=lesson.id,
        title="Публичное ДЗ",
        due_date=date(2026, 11, 2),
    )
    db_session.add(hw)
    await db_session.commit()
    await db_session.refresh(hw)
    log_homework_event(
        db_session, test_user, ACTION_CREATED, hw.id, snapshot_changes(hw)
    )
    await db_session.commit()

    page = await client.get("/admin/history", headers=auth_headers)
    assert page.status_code == 200
    assert "Создал" in page.text
    assert "Публичное ДЗ" in page.text
    assert "student" in page.text
    assert "Алгебра · Пн, 1 урок" in page.text
    # Creation: values only, no "old → new" noise
    assert "→" not in page.text

    log_homework_event(
        db_session,
        test_user,
        ACTION_UPDATED,
        hw.id,
        {"title": ["Публичное ДЗ", "Тихое ДЗ"]},
    )
    await db_session.commit()

    updated_page = await client.get("/admin/history", headers=auth_headers)
    assert "Изменил" in updated_page.text
    assert "Тихое ДЗ" in updated_page.text
    assert "→" in updated_page.text
    # Subject and date must be present in the update entry
    assert "Предмет:" in updated_page.text
    assert "Алгебра" in updated_page.text
    assert "Дата:" in updated_page.text
    assert "02.11.2026" in updated_page.text

    # When the homework is later deleted, update log entry still displays subject and date via context
    log_homework_event(
        db_session,
        test_user,
        "deleted",
        None,
        snapshot_changes(hw, deleted=True),
    )
    await db_session.delete(hw)
    await db_session.commit()

    after_delete_page = await client.get("/admin/history", headers=auth_headers)
    assert after_delete_page.status_code == 200
    assert "Удалил" in after_delete_page.text
    assert "Изменил" in after_delete_page.text
    assert "Алгебра" in after_delete_page.text
    assert "02.11.2026" in after_delete_page.text

    forbidden = await client.get("/admin/history", headers=regular_auth_headers)
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_admin_history_update_retains_subject_and_date_after_deletion(
    client: AsyncClient,
    db_session: AsyncSession,
    test_subject: Subject,
    auth_headers: dict,
):
    """Update events must retain subject and date in admin logs even if homework is deleted later."""
    # 1. Create homework
    created = await client.post(
        "/api/v1/homework",
        json={
            "subject_id": test_subject.id,
            "title": "Первая версия",
            "due_date": "2026-11-09",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    hw_id = created.json()["id"]

    # 2. Update homework text
    updated = await client.put(
        f"/api/v1/homework/{hw_id}",
        json={"title": "Вторая версия"},
        headers=auth_headers,
    )
    assert updated.status_code == 200

    # 3. Delete homework (foreign key sets homework_id = NULL on event records)
    deleted = await client.delete(f"/api/v1/homework/{hw_id}", headers=auth_headers)
    assert deleted.status_code == 204

    # 4. History page must still display subject and date for the update entry
    page = await client.get("/admin/history", headers=auth_headers)
    assert page.status_code == 200
    assert "Изменил" in page.text
    assert "Первая версия" in page.text
    assert "Вторая версия" in page.text
    assert "Алгебра" in page.text
    assert "09.11.2026" in page.text
