"""Web Push delivery for homework changes.

A notification is queued through FastAPI BackgroundTasks so the HTTP response
is not delayed by calls to the browser push services.
"""

import asyncio
import json
import logging
from datetime import date
from typing import Optional
from urllib.parse import urlparse

from fastapi import BackgroundTasks
from pywebpush import WebPushException, webpush
from sqlalchemy import delete, or_, select

from locus.config import get_settings
from locus.database import async_session_maker
from locus.homework_audit import ACTION_CREATED, ACTION_DELETED, ACTION_UPDATED
from locus.models.push_subscription import PushSubscription
from locus.models.user import User

logger = logging.getLogger(__name__)

STALE_STATUSES = (404, 410)

# Only known browser push services: the endpoint is later POSTed to by the server,
# so an arbitrary URL here would be an SSRF hole.
ALLOWED_PUSH_DOMAINS = (
    "googleapis.com",
    "google.com",
    "push.services.mozilla.com",
    "services.mozilla.com",
    "notify.windows.com",
    "push.apple.com",
)
DISALLOWED_HOSTS = (
    "script.google.com",
)


def push_enabled() -> bool:
    settings = get_settings()
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def is_allowed_endpoint(endpoint: str) -> bool:
    url = urlparse(endpoint)
    host = (url.hostname or "").lower()
    if url.scheme != "https" or not host:
        return False
    if url.port not in (None, 443):
        return False
    if url.username or url.password:
        return False
    if host in DISALLOWED_HOSTS:
        return False
    return any(
        host == domain or host.endswith("." + domain)
        for domain in ALLOWED_PUSH_DOMAINS
    )


def _normalize_vapid_subject(subject: str) -> str:
    cleaned = (subject or "").strip()
    if not cleaned:
        return "mailto:admin@example.com"
    if "@" in cleaned and not cleaned.startswith(("mailto:", "http://", "https://")):
        return f"mailto:{cleaned}"
    return cleaned


def notify_homework_change(
    background: BackgroundTasks,
    actor: User,
    action: str,
    hw_id: int,
    title: str,
    subject_name: str,
    subgroup: Optional[object],
    due_date: Optional[date],
) -> None:
    if not push_enabled():
        return

    subject_part = f" · {subject_name}" if subject_name else ""
    if action == ACTION_CREATED:
        heading = f"Новое ДЗ{subject_part}"
        body = f"{title} · до {due_date.strftime('%d.%m')}" if due_date else title
    elif action == ACTION_UPDATED:
        heading = f"ДЗ изменено{subject_part}"
        body = f"{title} (@{actor.username})"
    elif action == ACTION_DELETED:
        heading = f"ДЗ удалено{subject_part}"
        body = title
    else:
        return

    payload = {
        "title": heading,
        "body": body,
        "tag": f"hw-{hw_id}",
        "url": "/homework",
    }
    background.add_task(_send_push, actor.id, subgroup, payload)


async def _send_push(actor_id: int, subgroup: Optional[object], payload: dict) -> None:
    settings = get_settings()
    try:
        # Step 1: Query subscriptions and close DB session immediately so
        # connections are not held idle during outbound HTTP requests.
        async with async_session_maker() as db:
            stmt = (
                select(PushSubscription)
                .join(User, PushSubscription.user_id == User.id)
                .where(User.is_active.is_(True), User.id != actor_id)
            )
            if subgroup is not None and str(subgroup).strip():
                sub_str = str(subgroup).strip()
                if sub_str in ("1", "2"):
                    stmt = stmt.where(or_(User.subgroup.is_(None), User.subgroup == int(sub_str)))
                elif sub_str in ("boys", "girls"):
                    stmt = stmt.where(or_(User.gender_subgroup.is_(None), User.gender_subgroup == sub_str))
            raw_subs = list((await db.execute(stmt)).scalars().all())

        if not raw_subs:
            return

        # Extract primitive values to avoid sharing live ORM instances across threads,
        # with defense-in-depth endpoint validation.
        targets = [
            (sub.id, sub.endpoint, sub.p256dh, sub.auth)
            for sub in raw_subs
            if is_allowed_endpoint(sub.endpoint)
        ]
        if not targets:
            return

        data = json.dumps(payload, ensure_ascii=False)
        semaphore = asyncio.Semaphore(10)

        async def _bounded_send(
            sub_id: int, endpoint: str, p256dh: str, auth: str
        ) -> tuple[int, Optional[int]]:
            async with semaphore:
                status = await asyncio.to_thread(
                    _send_one, settings, sub_id, endpoint, p256dh, auth, data
                )
                return sub_id, status

        results = await asyncio.gather(
            *(
                _bounded_send(sub_id, endpoint, p256dh, auth)
                for sub_id, endpoint, p256dh, auth in targets
            )
        )

        stale = [sub_id for sub_id, status in results if status in STALE_STATUSES]
        if stale:
            async with async_session_maker() as db:
                await db.execute(
                    delete(PushSubscription).where(PushSubscription.id.in_(stale))
                )
                await db.commit()
    except Exception:
        logger.exception("Failed to send push notifications for payload %s", payload.get("tag"))


def _send_one(
    settings,
    sub_id: int,
    endpoint: str,
    p256dh: str,
    auth: str,
    data: str,
) -> Optional[int]:
    try:
        webpush(
            subscription_info={
                "endpoint": endpoint,
                "keys": {"p256dh": p256dh, "auth": auth},
            },
            data=data,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": _normalize_vapid_subject(settings.VAPID_SUBJECT)},
            timeout=10,
        )
        return None
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else None
        logger.info("Push failed for subscription %s: %s", sub_id, status or exc)
        return status
    except Exception:
        logger.exception("Push failed for subscription %s", sub_id)
        return None
