import re
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.models.api_key import ApiKey
from locus.models.homework import Homework
from locus.models.homework_event import HomeworkEvent
from locus.models.lesson import Lesson
from locus.models.subject import Subject
from locus.models.user import User
from locus.security import generate_api_key, hash_api_key


@pytest.mark.asyncio
async def test_api_key_authenticates_requests(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
):
    key = generate_api_key()
    db_session.add(ApiKey(name="bot", key_hash=hash_api_key(key), user_id=test_user.id))
    await db_session.commit()

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "student"

    unknown = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer lk_unknown"}
    )
    assert unknown.status_code == 401


@pytest.mark.asyncio
async def test_revoked_api_key_is_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
):
    key = generate_api_key()
    api_key = ApiKey(name="bot", key_hash=hash_api_key(key), user_id=test_user.id)
    db_session.add(api_key)
    await db_session.commit()

    await db_session.delete(api_key)
    await db_session.commit()

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_creates_and_revokes_api_key(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    auth_headers: dict,
    regular_auth_headers: dict,
):
    forbidden = await client.get("/admin/api-keys", headers=regular_auth_headers)
    assert forbidden.status_code == 403

    created = await client.post(
        "/admin/api-keys",
        data={"name": "Telegram-бот", "user_id": test_user.id},
        headers=auth_headers,
    )
    assert created.status_code == 303

    page = await client.get("/admin/api-keys", headers=auth_headers)
    assert page.status_code == 200
    assert "Telegram-бот" in page.text

    new_key = re.search(r"(lk_[A-Za-z0-9_-]+)", page.text)
    assert new_key, "plaintext key must be shown once"

    stored = (await db_session.execute(select(ApiKey))).scalar_one()
    assert stored.key_hash == hash_api_key(new_key.group(1))
    assert new_key.group(1) not in stored.key_hash

    # Reloading the page must not create or show another key
    reloaded = await client.get("/admin/api-keys", headers=auth_headers)
    assert new_key.group(1) not in reloaded.text
    assert await db_session.scalar(select(ApiKey)) is stored

    # The freshly created key works against the public API
    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {new_key.group(1)}"},
    )
    assert me.status_code == 200

    removed = await client.post(
        f"/admin/api-keys/{stored.id}/delete", headers=auth_headers
    )
    assert removed.status_code == 303
    assert await db_session.scalar(select(ApiKey)) is None


@pytest.mark.asyncio
async def test_day_summary_pairs_homework_with_lessons(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    test_subject: Subject,
):
    lesson = Lesson(
        subject_id=test_subject.id,
        day_of_week=1,
        lesson_number=2,
        start_time="08:55",
        end_time="09:40",
        week_type="ALL",
        room="12",
    )
    db_session.add(lesson)
    await db_session.commit()
    await db_session.refresh(lesson)

    target = "2026-11-02"
    db_session.add_all(
        [
            Homework(
                subject_id=test_subject.id,
                lesson_id=lesson.id,
                title="К уроку",
                due_date=date.fromisoformat(target),
            ),
            Homework(
                subject_id=test_subject.id,
                title="Без урока",
                due_date=date.fromisoformat(target),
            ),
        ]
    )
    await db_session.commit()

    key = generate_api_key()
    db_session.add(ApiKey(name="bot", key_hash=hash_api_key(key), user_id=test_user.id))
    await db_session.commit()

    response = await client.get(
        f"/api/v1/summary?date={target}",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["date"] == target
    assert data["day_of_week"] == 1
    assert data["day_name"] == "Понедельник"
    assert data["vacation"] is None

    # "Без урока" is matched to the lesson of the same subject
    assert len(data["lessons"]) == 1
    lesson_data = data["lessons"][0]
    assert lesson_data["lesson_number"] == 2
    assert lesson_data["subject"]["name"] == "Алгебра"
    assert lesson_data["teacher_name"] == "Иванова С.П."
    assert lesson_data["room"] == "12"
    assert {hw["title"] for hw in lesson_data["homework"]} == {"К уроку", "Без урока"}
    assert data["unassigned_homework"] == []


@pytest.mark.asyncio
async def test_api_key_changes_are_tagged_in_history(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    test_subject: Subject,
    auth_headers: dict,
):
    key = generate_api_key()
    db_session.add(ApiKey(name="Telegram-бот", key_hash=hash_api_key(key), user_id=test_user.id))
    await db_session.commit()

    created = await client.post(
        "/api/v1/homework",
        json={
            "subject_id": test_subject.id,
            "title": "Из бота",
            "due_date": "2026-11-02",
        },
        headers={"Authorization": f"Bearer {key}"},
    )
    assert created.status_code == 201

    event = (await db_session.execute(select(HomeworkEvent))).scalar_one()
    assert event.actor_username == "student"
    assert event.actor_key_name == "Telegram-бот"

    page = await client.get("/admin/history", headers=auth_headers)
    assert "student (Telegram-бот)" in page.text
