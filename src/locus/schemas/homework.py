from datetime import date, datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from locus.constants import HomeworkStatus
from locus.schemas.subject import SubjectOut


class HomeworkBase(BaseModel):
    subject_id: int
    lesson_id: Optional[int] = None
    title: str = Field(min_length=1, max_length=200)
    due_date: date
    subgroup: Optional[str] = None
    status: HomeworkStatus = HomeworkStatus.TODO

    @field_validator("subgroup", mode="before")
    @classmethod
    def normalize_subgroup(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        v_str = str(v).strip()
        if not v_str or v_str in ("0", "all", "none", "None"):
            return None
        if v_str not in ("1", "2", "boys", "girls"):
            raise ValueError("Подгруппа должна быть 1, 2, 'boys' или 'girls'")
        return v_str


class HomeworkIn(HomeworkBase):
    """Input-only rules. Output schemas must not inherit them: a stored row that
    breaks a rule (e.g. a legacy Sunday due_date) would fail the whole response."""

    @field_validator("due_date")
    @classmethod
    def validate_not_sunday(cls, v: date) -> date:
        if v.isoweekday() == 7:
            raise ValueError("Нельзя записать домашнее задание на воскресенье")
        return v


class HomeworkCreate(HomeworkIn):
    pass


class HomeworkUpdate(BaseModel):
    subject_id: Optional[int] = None
    lesson_id: Optional[int] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    due_date: Optional[date] = None
    subgroup: Optional[str] = None
    status: Optional[HomeworkStatus] = None

    @field_validator("subgroup", mode="before")
    @classmethod
    def normalize_subgroup(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        v_str = str(v).strip()
        if not v_str or v_str in ("0", "all", "none", "None"):
            return None
        if v_str not in ("1", "2", "boys", "girls"):
            raise ValueError("Подгруппа должна быть 1, 2, 'boys' или 'girls'")
        return v_str

    @field_validator("due_date")
    @classmethod
    def validate_not_sunday(cls, v: Optional[date]) -> Optional[date]:
        if v and v.isoweekday() == 7:
            raise ValueError("Нельзя записать домашнее задание на воскресенье")
        return v


class HomeworkStatusUpdate(BaseModel):
    status: HomeworkStatus


class HomeworkOut(HomeworkBase):
    id: int
    created_at: datetime
    updated_at: datetime
    subject: Optional[SubjectOut] = None

    model_config = ConfigDict(from_attributes=True)
