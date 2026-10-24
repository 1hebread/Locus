from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from locus.constants import HomeworkStatus
from locus.database import Base

if TYPE_CHECKING:
    from locus.models.homework import Homework
    from locus.models.user import User


def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HomeworkCompletion(Base):
    __tablename__ = "homework_completions"
    __table_args__ = (
        UniqueConstraint(
            "homework_id",
            "user_id",
            name="uq_homework_completions_homework_user",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    homework_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("homeworks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=HomeworkStatus.TODO.value,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=get_utc_now,
        onupdate=get_utc_now,
        nullable=False,
    )

    homework: Mapped["Homework"] = relationship(
        "Homework",
        back_populates="completions",
    )
    user: Mapped["User"] = relationship(
        "User",
        back_populates="homework_completions",
    )
