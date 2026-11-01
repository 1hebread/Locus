from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import locus.push as push_module
import locus.web.push_routes as push_routes
from locus.models.push_subscription import PushSubscription
from locus.models.user import User
from locus.security import hash_password

ENDPOINT = "https://fcm.googleapis.com/fcm/send/test-endpoint"


@pytest.mark.asyncio
async def test_push_config_is_disabled_without_vapid_keys(client: AsyncClient):
    response = await client.get("/push/config")
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "public_key": ""}


@pytest.mark.asyncio
async def test_subscribe_rejects_non_push_endpoint(
    client: AsyncClient, auth_cookies: dict, monkeypatch
):
    monkeypatch.setattr(push_routes, "push_enabled", lambda: True)
    client.cookies.update(auth_cookies)
    response = await client.post(
        "/push/subscribe",
        json={"endpoint": "https://127.0.0.1/internal", "keys": {"p256dh": "a", "auth": "b"}},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_subscribe_and_unsubscribe(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_cookies: dict,
    test_user: User,
    monkeypatch,
):
    monkeypatch.setattr(push_routes, "push_enabled", lambda: True)
    client.cookies.update(auth_cookies)
    long_endpoint = "https://sub.notify.windows.com/token?" + "a" * 700
    body = {"endpoint": long_endpoint, "keys": {"p256dh": "key", "auth": "secret"}}

    assert (await client.post("/push/subscribe", json=body)).status_code == 200
    saved = await db_session.scalar(select(PushSubscription))
    assert (saved.user_id, saved.p256dh, saved.auth) == (test_user.id, "key", "secret")
    assert saved.endpoint == long_endpoint

    # Same browser, updated keys: update in place instead of a duplicate row
    body["keys"] = {"p256dh": "key2", "auth": "secret2"}
    assert (await client.post("/push/subscribe", json=body)).status_code == 200
    subscriptions = list((await db_session.execute(select(PushSubscription))).scalars())
    assert len(subscriptions) == 1
    assert subscriptions[0].p256dh == "key2"

    assert (
        await client.post("/push/unsubscribe", json={"endpoint": long_endpoint})
    ).status_code == 200
    assert await db_session.scalar(select(PushSubscription)) is None


@pytest.mark.asyncio
async def test_logout_removes_only_this_browser_subscription(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_cookies: dict,
    test_user: User,
):
    client.cookies.update(auth_cookies)
    other_user = User(username="other", hashed_password=hash_password("x"))
    db_session.add(other_user)
    await db_session.flush()
    db_session.add_all(
        [
            PushSubscription(
                user_id=test_user.id, endpoint=ENDPOINT, p256dh="key", auth="secret"
            ),
            PushSubscription(
                user_id=other_user.id,
                endpoint=f"{ENDPOINT}-other",
                p256dh="key",
                auth="secret",
            ),
        ]
    )
    await db_session.commit()

    response = await client.post("/auth/logout", data={"push_endpoint": ENDPOINT})
    assert response.status_code == 303

    remaining = {
        row.endpoint
        for row in (await db_session.execute(select(PushSubscription))).scalars()
    }
    assert remaining == {f"{ENDPOINT}-other"}


@pytest.mark.asyncio
async def test_send_push_filters_recipients(
    db_session: AsyncSession, test_user: User, monkeypatch
):
    users = [
        (test_user, None, True),  # actor: never receives their own change
        (User(username="sub1", hashed_password=hash_password("x"), subgroup=1), 1, True),
        (User(username="sub2", hashed_password=hash_password("x"), subgroup=2), 2, True),
        (User(username="teacher", hashed_password=hash_password("x"), subgroup=None), None, True),
        (User(username="gone", hashed_password=hash_password("x"), subgroup=1, is_active=False), 1, False),
    ]
    for user, _, _ in users:
        db_session.add(user)
    await db_session.flush()
    for index, (user, _, _) in enumerate(users):
        db_session.add(
            PushSubscription(
                user_id=user.id,
                endpoint=f"{ENDPOINT}-{index}",
                p256dh="key",
                auth="secret",
            )
        )
    await db_session.commit()

    sent: list[str] = []

    class SessionMaker:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(push_module, "async_session_maker", lambda: SessionMaker())
    monkeypatch.setattr(
        push_module,
        "get_settings",
        lambda: SimpleNamespace(VAPID_PRIVATE_KEY="key", VAPID_SUBJECT="mailto:test@example.com"),
    )
    monkeypatch.setattr(
        push_module,
        "webpush",
        lambda subscription_info, **kwargs: sent.append(subscription_info["endpoint"]),
    )

    await push_module._send_push(test_user.id, subgroup=1, payload={"title": "x"})

    assert sorted(sent) == sorted([f"{ENDPOINT}-1", f"{ENDPOINT}-3"])


def test_is_allowed_endpoint():
    assert push_module.is_allowed_endpoint("https://push.apple.com/v1/token") is True
    assert push_module.is_allowed_endpoint("https://web.push.apple.com/v1/token") is True
    assert push_module.is_allowed_endpoint("https://sub.notify.windows.com/token") is True
    assert push_module.is_allowed_endpoint("https://notify.windows.com/token") is True
    assert push_module.is_allowed_endpoint("https://updates.push.services.mozilla.com/push/v1") is True
    assert push_module.is_allowed_endpoint("https://push.services.mozilla.com/v1") is True
    assert push_module.is_allowed_endpoint("https://fcm.googleapis.com/fcm/send/abc") is True
    assert push_module.is_allowed_endpoint("https://android.googleapis.com/gcm/send/abc") is True
    assert push_module.is_allowed_endpoint("https://jmt17.google.com/test") is True
    assert push_module.is_allowed_endpoint("https://script.google.com/macros/exec") is False
    assert push_module.is_allowed_endpoint("https://fcm.googleapis.com:8080/send") is False
    assert push_module.is_allowed_endpoint("https://user:pass@fcm.googleapis.com/send") is False
    assert push_module.is_allowed_endpoint("https://evil.example.com/endpoint") is False
    assert push_module.is_allowed_endpoint("https://fakegoogleapis.com/test") is False
    assert push_module.is_allowed_endpoint("http://push.apple.com/token") is False
    assert push_module.is_allowed_endpoint("not-a-url") is False


def test_normalize_vapid_subject():
    assert push_module._normalize_vapid_subject("admin@school.ru") == "mailto:admin@school.ru"
    assert push_module._normalize_vapid_subject("mailto:admin@school.ru") == "mailto:admin@school.ru"
    assert push_module._normalize_vapid_subject("https://school.ru") == "https://school.ru"
    assert push_module._normalize_vapid_subject("") == "mailto:admin@example.com"


def test_notify_homework_change_payload_formatting(monkeypatch):
    from datetime import date
    from fastapi import BackgroundTasks
    from locus.homework_audit import ACTION_CREATED, ACTION_DELETED, ACTION_UPDATED

    monkeypatch.setattr(push_module, "push_enabled", lambda: True)

    bg = BackgroundTasks()
    actor = SimpleNamespace(id=1, username="ivanov")

    # Created with date and subject
    notify_homework_change = push_module.notify_homework_change
    notify_homework_change(
        bg, actor, ACTION_CREATED, 10, "Стр. 55", "Алгебра", None, date(2026, 11, 5)
    )
    task = bg.tasks[-1]
    assert task.args[0] == 1
    assert task.args[1] is None
    assert task.args[2]["title"] == "Новое ДЗ · Алгебра"
    assert task.args[2]["body"] == "Стр. 55 · до 05.11"
    assert task.args[2]["tag"] == "hw-10"

    # Updated with subject
    notify_homework_change(
        bg, actor, ACTION_UPDATED, 10, "Стр. 56", "Алгебра", 1, None
    )
    task = bg.tasks[-1]
    assert task.args[1] == 1
    assert task.args[2]["title"] == "ДЗ изменено · Алгебра"
    assert task.args[2]["body"] == "Стр. 56 (@ivanov)"

    # Deleted without subject (clean title without dangling dot)
    notify_homework_change(
        bg, actor, ACTION_DELETED, 10, "Стр. 56", "", None, None
    )
    task = bg.tasks[-1]
    assert task.args[2]["title"] == "ДЗ удалено"
    assert task.args[2]["body"] == "Стр. 56"


@pytest.mark.asyncio
async def test_send_push_removes_stale_subscriptions(
    db_session: AsyncSession, test_user: User, monkeypatch
):
    sub_active = PushSubscription(
        user_id=test_user.id, endpoint=f"{ENDPOINT}-active", p256dh="k1", auth="s1"
    )
    sub_stale = PushSubscription(
        user_id=test_user.id, endpoint=f"{ENDPOINT}-stale", p256dh="k2", auth="s2"
    )
    db_session.add_all([sub_active, sub_stale])
    await db_session.commit()
    await db_session.refresh(sub_active)
    await db_session.refresh(sub_stale)

    class MockResponse:
        def __init__(self, status_code):
            self.status_code = status_code

    class SessionMaker:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    def mock_webpush(subscription_info, **kwargs):
        if subscription_info["endpoint"] == f"{ENDPOINT}-stale":
            from pywebpush import WebPushException
            raise WebPushException("Gone", response=MockResponse(410))

    monkeypatch.setattr(push_module, "async_session_maker", lambda: SessionMaker())
    monkeypatch.setattr(
        push_module,
        "get_settings",
        lambda: SimpleNamespace(
            VAPID_PRIVATE_KEY="key", VAPID_SUBJECT="mailto:test@example.com"
        ),
    )
    monkeypatch.setattr(push_module, "webpush", mock_webpush)

    # Actor id 999 so test_user's subscriptions are included
    await push_module._send_push(999, subgroup=None, payload={"title": "test"})

    remaining = list((await db_session.execute(select(PushSubscription))).scalars().all())
    assert len(remaining) == 1
    assert remaining[0].endpoint == f"{ENDPOINT}-active"
