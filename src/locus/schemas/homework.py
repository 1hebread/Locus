from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from locus.constants import HomeworkStatus
from locus.schemas.subject import SubjectOut


class HomeworkBase(BaseModel):
    subject_id: int
    lesson_id: Optional[int] = None
    title: str = Field(min_length=1, max_length=200)
    due_date: date
    subgroup: Optional[int] = Field(default=None, ge=1, le=2)
    status: HomeworkStatus = HomeworkStatus.TODO

    @field_validator("due_date")
    @classmethod
    def validate_not_sunday(cls, v: date) -> date:
        if v.isoweekday() == 7:
            raise ValueError("Нельзя записать домашнее задание на воскресенье")
        return v


class HomeworkCreate(HomeworkBase):
    pass


class HomeworkUpdate(BaseModel):
    subject_id: Optional[int] = None
    lesson_id: Optional[int] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    due_date: Optional[date] = None
    subgroup: Optional[int] = Field(default=None, ge=1, le=2)
    status: Optional[HomeworkStatus] = None

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
