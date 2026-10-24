from datetime import date
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VacationBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Название каникул не может быть пустым")
        return v

    @model_validator(mode="after")
    def validate_date_range(self) -> "VacationBase":
        if self.start_date > self.end_date:
            raise ValueError("Дата окончания не может быть раньше даты начала")
        return self


class VacationCreate(VacationBase):
    pass


class VacationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Название каникул не может быть пустым")
        return v

    @model_validator(mode="after")
    def validate_date_range(self) -> "VacationUpdate":
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("Дата окончания не может быть раньше даты начала")
        return self


class VacationOut(VacationBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
