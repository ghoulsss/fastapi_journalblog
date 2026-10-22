from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from src.db.models import CheckAuthor


class UserCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    email: EmailStr


class UserSecretSchema(UserCreateSchema):
    password: str = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        if len(value.encode()) > 72:
            raise ValueError("Password must not exceed 72 UTF-8 bytes")
        return value


class UserSchema(UserCreateSchema):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_author: CheckAuthor
    active: bool
