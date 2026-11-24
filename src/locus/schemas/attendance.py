from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from locus.constants import AttendanceStatus
from locus.schemas.vacation import VacationOut


class AttendanceStudentOut(BaseModel):
    id: int
    full_name: str
    is_active: bool = True
    status: Optional[str] = None


class AttendanceCounts(BaseModel):
    present: int = 0
    absent: int = 0
    late: int = 0
    excused: int = 0
    sick: int = 0
    unmarked: int = 0


class AttendanceDayOut(BaseModel):
    date: date
    day_of_week: int
    day_name: str
    is_school_day: bool
    is_editable: bool
    vacation: Optional[VacationOut] = None
    students: List[AttendanceStudentOut]
    counts: AttendanceCounts


class AttendanceMarkIn(BaseModel):
    student_id: int
    status: Optional[AttendanceStatus]


class AttendanceMarksUpdate(BaseModel):
    marks: List[AttendanceMarkIn] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_unique_students(self) -> "AttendanceMarksUpdate":
        student_ids = [mark.student_id for mark in self.marks]
        if len(student_ids) != len(set(student_ids)):
            raise ValueError("Ученики в списке отметок не должны повторяться")
        return self
