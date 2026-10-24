from datetime import date
from sqlalchemy import Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from locus.database import Base


class Vacation(Base):
    __tablename__ = "vacations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
