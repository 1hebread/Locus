from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class UserLogin(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    is_active: bool
    is_admin: bool
    subgroup: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
