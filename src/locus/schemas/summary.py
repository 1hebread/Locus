from datetime import date
from typing import List, Optional

from pydantic import BaseModel

from locus.schemas.homework import HomeworkOut
from locus.schemas.subject import SubjectOut
from locus.schemas.vacation import VacationOut


class SummaryLesson(BaseModel):
    lesson_number: int
    start_time: str
    end_time: str
    room: Optional[str] = None
    teacher_name: Optional[str] = None
    subgroup: Optional[int] = None
    subject: Optional[SubjectOut] = None
    homework: List[HomeworkOut] = []


class DaySummary(BaseModel):
    date: date
    day_of_week: int
    day_name: str
    vacation: Optional[VacationOut] = None
    lessons: List[SummaryLesson] = []
    unassigned_homework: List[HomeworkOut] = []
