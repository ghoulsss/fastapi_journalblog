from pydantic import BaseModel, EmailStr

from src.db.models import CheckAuthor


class UserCreateSchema(BaseModel):
    username: str
    email: EmailStr


class UserCreateSchema(UserCreateSchema):
    password: str


class UserSchema(UserCreateSchema):
    id: int
    is_author: CheckAuthor
    # articles добавить для вывода постов пользователя мб

    class Config:
        from_attributes = True


class UserSchemaTest(BaseModel):
    username: str
    password: bytes
    email: EmailStr
    active: bool = True
