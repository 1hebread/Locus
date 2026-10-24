from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

from locus.constants import DEFAULT_BELL_SCHEDULE, WeekType
from locus.schemas.subject import SubjectOut


class LessonBase(BaseModel):
    subject_id: int
    day_of_week: int = Field(ge=1, le=7)
    lesson_number: int = Field(ge=1, le=8)
    start_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    end_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    week_type: WeekType = WeekType.ALL
    room: Optional[str] = Field(default=None, max_length=50)
    note: Optional[str] = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def populate_default_times(self) -> "LessonBase":
        """Auto-populate default school bell times if omitted."""
        if not self.start_time or not self.end_time:
            default_slot = DEFAULT_BELL_SCHEDULE.get(self.lesson_number)
            if default_slot:
                if not self.start_time:
                    self.start_time = default_slot[0]
                if not self.end_time:
                    self.end_time = default_slot[1]
        return self


class LessonCreate(LessonBase):
    pass


class LessonUpdate(BaseModel):
    subject_id: Optional[int] = None
    day_of_week: Optional[int] = Field(default=None, ge=1, le=7)
    lesson_number: Optional[int] = Field(default=None, ge=1, le=8)
    start_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    end_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    week_type: Optional[WeekType] = None
    room: Optional[str] = Field(default=None, max_length=50)
    note: Optional[str] = Field(default=None, max_length=255)


class LessonOut(BaseModel):
    id: int
    subject_id: int
    day_of_week: int
    lesson_number: int
    start_time: str
    end_time: str
    week_type: str
    room: Optional[str] = None
    note: Optional[str] = None
    subject: Optional[SubjectOut] = None

    model_config = ConfigDict(from_attributes=True)
