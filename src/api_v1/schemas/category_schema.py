from pydantic import BaseModel, ConfigDict, Field


class CategoryCreateSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=100)


class CategorySchema(CategoryCreateSchema):
    model_config = ConfigDict(from_attributes=True)
    id: int
