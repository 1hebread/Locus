from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from locus.constants import WeekType
from locus.database import Base

if TYPE_CHECKING:
    from locus.models.subject import Subject
    from locus.models.homework import Homework


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    subject_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subjects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 1=Mon .. 7=Sun
    lesson_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..8
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)  # "08:30"
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)  # "09:15"
    week_type: Mapped[str] = mapped_column(
        String(20),
        default=WeekType.ALL.value,
        nullable=False,
    )
    room: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    subgroup: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    subject: Mapped["Subject"] = relationship("Subject", back_populates="lessons")
    homeworks: Mapped[List["Homework"]] = relationship(
        "Homework",
        back_populates="lesson",
    )

    @property
    def effective_teacher_name(self) -> Optional[str]:
        if self.subject:
            return self.subject.get_teacher_name(self.subgroup)
        return None

    @property
    def effective_room(self) -> Optional[str]:
        if self.room:
            return self.room
        if self.subject:
            return self.subject.get_room(self.subgroup)
        return None

    @property
    def effective_teacher_phone(self) -> Optional[str]:
        if self.subject:
            return self.subject.get_teacher_phone(self.subgroup)
        return None

    @property
    def effective_whatsapp_url(self) -> Optional[str]:
        if self.subject:
            return self.subject.get_whatsapp_url(self.subgroup)
        return None
