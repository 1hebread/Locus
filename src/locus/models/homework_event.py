from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from locus.database import Base


def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HomeworkEvent(Base):
    __tablename__ = "homework_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    homework_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("homeworks.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    actor_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Snapshot: the log must survive user deletion
    actor_username: Mapped[str] = mapped_column(String(100), nullable=False)
    # Set when the change came through an API key: name of that key
    actor_key_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    # field -> [old value, new value]
    changes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=get_utc_now,
        index=True,
        nullable=False,
    )
