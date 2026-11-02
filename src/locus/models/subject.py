from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from locus.crypto import EncryptedString, format_whatsapp_url
from locus.database import Base

if TYPE_CHECKING:
    from locus.models.lesson import Lesson
    from locus.models.homework import Homework


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    teacher_name: Mapped[Optional[str]] = mapped_column(EncryptedString(), nullable=True)
    teacher_phone: Mapped[Optional[str]] = mapped_column(EncryptedString(), nullable=True)
    room: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Subgroup 2 teacher/room details (if different from default/subgroup 1)
    teacher2_name: Mapped[Optional[str]] = mapped_column(EncryptedString(), nullable=True)
    teacher2_phone: Mapped[Optional[str]] = mapped_column(EncryptedString(), nullable=True)
    room2: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    lessons: Mapped[List["Lesson"]] = relationship(
        "Lesson",
        back_populates="subject",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    homeworks: Mapped[List["Homework"]] = relationship(
        "Homework",
        back_populates="subject",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def whatsapp_url(self) -> Optional[str]:
        return format_whatsapp_url(self.teacher_phone)

    @property
    def whatsapp2_url(self) -> Optional[str]:
        return format_whatsapp_url(self.teacher2_phone)

    def get_teacher_name(self, subgroup: Optional[object] = None) -> Optional[str]:
        if str(subgroup) in ("2", "girls"):
            return self.teacher2_name
        return self.teacher_name

    def get_teacher_phone(self, subgroup: Optional[object] = None) -> Optional[str]:
        if str(subgroup) in ("2", "girls"):
            return self.teacher2_phone
        return self.teacher_phone

    def get_whatsapp_url(self, subgroup: Optional[object] = None) -> Optional[str]:
        if str(subgroup) in ("2", "girls"):
            return self.whatsapp2_url
        return self.whatsapp_url

    def get_room(self, subgroup: Optional[object] = None) -> Optional[str]:
        if str(subgroup) in ("2", "girls"):
            return self.room2
        return self.room
