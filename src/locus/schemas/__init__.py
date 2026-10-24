from locus.schemas.auth import Token, UserLogin, UserOut
from locus.schemas.subject import SubjectCreate, SubjectOut, SubjectUpdate
from locus.schemas.lesson import LessonCreate, LessonOut, LessonUpdate
from locus.schemas.homework import (
    HomeworkCreate,
    HomeworkOut,
    HomeworkStatusUpdate,
    HomeworkUpdate,
)

from locus.schemas.vacation import (
    VacationBase,
    VacationCreate,
    VacationOut,
    VacationUpdate,
)

__all__ = [
    "Token",
    "UserLogin",
    "UserOut",
    "SubjectCreate",
    "SubjectOut",
    "SubjectUpdate",
    "LessonCreate",
    "LessonOut",
    "LessonUpdate",
    "HomeworkCreate",
    "HomeworkOut",
    "HomeworkStatusUpdate",
    "HomeworkUpdate",
    "VacationBase",
    "VacationCreate",
    "VacationOut",
    "VacationUpdate",
]
