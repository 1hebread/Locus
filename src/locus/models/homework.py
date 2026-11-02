from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from locus.database import Base

if TYPE_CHECKING:
    from locus.models.homework_completion import HomeworkCompletion
    from locus.models.subject import Subject
    from locus.models.lesson import Lesson


def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Homework(Base):
    __tablename__ = "homeworks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    subject_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subjects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    lesson_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("lessons.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    subgroup: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=get_utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=get_utc_now,
        onupdate=get_utc_now,
        nullable=False,
    )

    subject: Mapped["Subject"] = relationship("Subject", back_populates="homeworks")
    lesson: Mapped[Optional["Lesson"]] = relationship("Lesson", back_populates="homeworks")
    completions: Mapped[List["HomeworkCompletion"]] = relationship(
        "HomeworkCompletion",
        back_populates="homework",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
