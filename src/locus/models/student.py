from datetime import datetime, timezone
from typing import TYPE_CHECKING, List

from sqlalchemy import Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from locus.crypto import EncryptedString
from locus.database import Base

if TYPE_CHECKING:
    from locus.models.attendance import AttendanceRecord


def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Encrypted at rest. Fernet ciphertext is non-deterministic, so the roster
    # is sorted in Python rather than with SQL ORDER BY.
    full_name: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    # Archived instead of deleted so past attendance stays readable
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=get_utc_now,
        nullable=False,
    )

    attendance_records: Mapped[List["AttendanceRecord"]] = relationship(
        "AttendanceRecord",
        back_populates="student",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
