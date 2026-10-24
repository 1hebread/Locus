import re
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SubjectBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    teacher_name: Optional[str] = Field(default=None, max_length=120)
    teacher_phone: Optional[str] = Field(default=None, max_length=50)
    room: Optional[str] = Field(default=None, max_length=50)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Название предмета не может быть пустым")
        return v

    @field_validator("teacher_name", "room")
    @classmethod
    def strip_text(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            return v if v else None
        return None

    @field_validator("teacher_phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                return None
            if not re.fullmatch(r"[\d\s\+\-\(\)]+", v):
                raise ValueError("Номер телефона может содержать только цифры и символы +, -, (, )")
            digits = re.sub(r"\D", "", v)
            if len(digits) < 7:
                raise ValueError("Номер телефона должен содержать не менее 7 цифр")
            return v
        return None


class SubjectCreate(SubjectBase):
    pass


class SubjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    teacher_name: Optional[str] = Field(default=None, max_length=120)
    teacher_phone: Optional[str] = Field(default=None, max_length=50)
    room: Optional[str] = Field(default=None, max_length=50)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Название предмета не может быть пустым")
            return v
        return None

    @field_validator("teacher_name", "room")
    @classmethod
    def strip_text(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            return v if v else None
        return None

    @field_validator("teacher_phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                return None
            if not re.fullmatch(r"[\d\s\+\-\(\)]+", v):
                raise ValueError("Номер телефона может содержать только цифры и символы +, -, (, )")
            digits = re.sub(r"\D", "", v)
            if len(digits) < 7:
                raise ValueError("Номер телефона должен содержать не менее 7 цифр")
            return v
        return None


class SubjectOut(SubjectBase):
    id: int
    whatsapp_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
