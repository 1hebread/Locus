from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from locus.constants import DEFAULT_BELL_SCHEDULE, WeekType
from locus.schemas.subject import SubjectOut


TIME_PATTERN = r"^(?:[01]\d|2[0-3]):[0-5]\d$"


class LessonBase(BaseModel):
    subject_id: int
    day_of_week: int = Field(ge=1, le=7)
    lesson_number: int = Field(ge=1, le=8)
    start_time: Optional[str] = Field(default=None, pattern=TIME_PATTERN)
    end_time: Optional[str] = Field(default=None, pattern=TIME_PATTERN)
    week_type: WeekType = WeekType.ALL
    room: Optional[str] = Field(default=None, max_length=50)
    note: Optional[str] = Field(default=None, max_length=255)
    subgroup: Optional[str] = None

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

    @field_validator("room", "note")
    @classmethod
    def strip_text(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            return v if v else None
        return None

    @model_validator(mode="after")
    def populate_and_validate_times(self) -> "LessonBase":
        """Auto-populate default school bell times if omitted and validate order."""
        if not self.start_time or not self.end_time:
            default_slot = DEFAULT_BELL_SCHEDULE.get(self.lesson_number)
            if default_slot:
                if not self.start_time:
                    self.start_time = default_slot[0]
                if not self.end_time:
                    self.end_time = default_slot[1]
        if self.start_time and self.end_time:
            if self.start_time >= self.end_time:
                raise ValueError("Время окончания урока должно быть позже времени начала")
        return self


class LessonCreate(LessonBase):
    pass


class LessonUpdate(BaseModel):
    subject_id: Optional[int] = None
    day_of_week: Optional[int] = Field(default=None, ge=1, le=7)
    lesson_number: Optional[int] = Field(default=None, ge=1, le=8)
    start_time: Optional[str] = Field(default=None, pattern=TIME_PATTERN)
    end_time: Optional[str] = Field(default=None, pattern=TIME_PATTERN)
    week_type: Optional[WeekType] = None
    room: Optional[str] = Field(default=None, max_length=50)
    note: Optional[str] = Field(default=None, max_length=255)
    subgroup: Optional[str] = None

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

    @field_validator("room", "note")
    @classmethod
    def strip_text(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            return v if v else None
        return None

    @field_validator(
        "subject_id",
        "day_of_week",
        "lesson_number",
        "start_time",
        "end_time",
        "week_type",
    )
    @classmethod
    def check_not_none(cls, v: Any, info) -> Any:
        if v is None:
            raise ValueError(f"Поле '{info.field_name}' не может быть пустым")
        return v

    @model_validator(mode="after")
    def validate_times(self) -> "LessonUpdate":
        if self.start_time and self.end_time:
            if self.start_time >= self.end_time:
                raise ValueError("Время окончания урока должно быть позже времени начала")
        return self


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
    subgroup: Optional[str] = None
    subject: Optional[SubjectOut] = None

    model_config = ConfigDict(from_attributes=True)
