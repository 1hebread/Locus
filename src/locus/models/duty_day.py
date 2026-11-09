from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from locus.database import Base


class DutyDay(Base):
    __tablename__ = "duty_days"

    day_of_week: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
