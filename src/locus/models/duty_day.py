from typing import Optional

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from locus.crypto import EncryptedString
from locus.database import Base


class DutyDay(Base):
    __tablename__ = "duty_days"

    day_of_week: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Empty rosters are stored as NULL: EncryptedString maps blank text to NULL.
    text: Mapped[Optional[str]] = mapped_column(EncryptedString(), nullable=True, default="")
