from pydantic import BaseModel, ConfigDict, Field


class TagCreateSchema(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=100)


class TagSchema(TagCreateSchema):
    model_config = ConfigDict(from_attributes=True)
    id: int
