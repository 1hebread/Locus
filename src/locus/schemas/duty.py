from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class DutyEntryOut(BaseModel):
    name: str
    login: Optional[str] = None
    linked: bool = False
    is_me: bool = False


class DutyDayUpdate(BaseModel):
    text: str = Field(max_length=2000)

    @field_validator("text")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()


class DutyDayOut(BaseModel):
    day_of_week: int
    name: str
    text: str
    entries: List[DutyEntryOut]
    is_today: bool
