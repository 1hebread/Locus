import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from locus.api.deps import get_current_user_web
from locus.config import get_settings
from locus.database import get_db
from locus.models.push_subscription import PushSubscription
from locus.models.user import User
from locus.push import is_allowed_endpoint, push_enabled

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/push", tags=["Push"])


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=500)
    auth: str = Field(min_length=1, max_length=200)


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=1024)
    keys: PushKeys


class PushEndpointIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=1024)


@router.get("/config")
async def push_config():
    """Public VAPID key for the browser subscription; empty when push is off."""
    settings = get_settings()
    enabled = push_enabled()
    return {
        "enabled": enabled,
        "public_key": settings.VAPID_PUBLIC_KEY if enabled else "",
    }


@router.post("/subscribe")
async def subscribe(
    data: PushSubscriptionIn,
    current_user: User = Depends(get_current_user_web),
    db: AsyncSession = Depends(get_db),
):
    if not push_enabled():
        raise HTTPException(status_code=503, detail="Уведомления не настроены на сервере")
    if not is_allowed_endpoint(data.endpoint):
        logger.warning("Rejected push endpoint for user %s: %s", current_user.username, data.endpoint)
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимый адрес push-сервиса: {data.endpoint}",
        )

    subscription = await db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == data.endpoint)
    )
    if subscription:
        # The same browser may log in as another user: move the endpoint over
        subscription.user_id = current_user.id
        subscription.p256dh = data.keys.p256dh
        subscription.auth = data.keys.auth
    else:
        db.add(
            PushSubscription(
                user_id=current_user.id,
                endpoint=data.endpoint,
                p256dh=data.keys.p256dh,
                auth=data.keys.auth,
            )
        )
    await db.commit()
    return {"ok": True}


@router.post("/unsubscribe")
async def unsubscribe(
    data: PushEndpointIn,
    current_user: User = Depends(get_current_user_web),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == data.endpoint,
            PushSubscription.user_id == current_user.id,
        )
    )
    await db.commit()
    return {"ok": True}
