from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.api_v1.schemas.category_schema import CategorySchema
from src.api_v1.schemas.tag_schema import TagSchema
from src.api_v1.schemas.user_schema import UserSchema
from src.db.models import IsPublished

PositiveId = Annotated[int, Field(gt=0)]


class ArticleCreateSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)
    category_id: PositiveId
    tag_ids: list[PositiveId] = Field(default_factory=list, max_length=100)
    is_published: IsPublished = IsPublished.nonpublished


class ArticleUpdateSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content: str | None = Field(default=None, min_length=1)
    category_id: PositiveId | None = None
    tag_ids: list[PositiveId] | None = Field(default=None, max_length=100)
    is_published: IsPublished | None = None

    @model_validator(mode="after")
    def reject_null_fields(self):
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Article fields cannot be null")
        return self


class ArticleSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    content: str
    category: CategorySchema
    user: list[UserSchema]
    tag: list[TagSchema]
    is_published: IsPublished
    created_at: datetime


class UserWithArticlesSchema(UserSchema):
    article: list[ArticleSchema]
