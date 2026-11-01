from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from locus.database import Base


def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # One browser endpoint belongs to exactly one user
    endpoint: Mapped[str] = mapped_column(String(1024), unique=True, index=True, nullable=False)
    p256dh: Mapped[str] = mapped_column(String(500), nullable=False)
    auth: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=get_utc_now,
        nullable=False,
    )
