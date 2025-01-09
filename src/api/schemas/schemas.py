from pydantic import BaseModel
from src.db.models import CheckAuthor, IsPublished, User


# Пользователи
class UserBaseSchema(BaseModel):
    login: str

    class Config:
        from_attributes = True


class UserCreateSchema(UserBaseSchema):
    password: str


class UserSchema(UserBaseSchema):
    id: int
    is_author: CheckAuthor


# Категории
class CategoryBaseSchema(BaseModel):
    name: str

    class Config:
        from_attributes = True


class CategoryCreateSchema(CategoryBaseSchema):
    pass


class CategorySchema(CategoryBaseSchema):
    id: int


# Теги
class TagBaseSchema(BaseModel):
    tag: str

    class Config:
        from_attributes = True


class TagCreateSchema(TagBaseSchema):
    pass


class TagSchema(TagBaseSchema):
    id: int


# Посты
class ArticleBaseSchema(BaseModel):
    title: str
    content: str
    author_id: int
    tags: list[int]
    category_id: int

    class Config:
        from_attributes = True


class ArticleCreateSchema(ArticleBaseSchema):
    pass


class ArticleSchema(ArticleBaseSchema):
    id: int
    is_published: IsPublished
