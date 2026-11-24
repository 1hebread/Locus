from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from locus.database import Base

if TYPE_CHECKING:
    from locus.models.student import Student


def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "attendance_date",
            name="uq_attendance_records_student_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("students.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    attendance_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # Who made the mark; the record survives user deletion
    marked_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=get_utc_now,
        onupdate=get_utc_now,
        nullable=False,
    )

    student: Mapped["Student"] = relationship("Student", back_populates="attendance_records")
