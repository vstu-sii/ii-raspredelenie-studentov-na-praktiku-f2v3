from pydantic import BaseModel, ConfigDict, Field, model_validator


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    teacher_id: int = Field(gt=0)
    count: int = Field(ge=1, le=50)


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    selections: list[Selection] = Field(min_length=1, max_length=100)
    focus: str | None = Field(default=None, max_length=1500)

    @model_validator(mode="after")
    def unique_teachers(self):
        ids = [s.teacher_id for s in self.selections]
        if len(ids) != len(set(ids)):
            raise ValueError("Repeated teacher_id")
        return self


class IntegrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str | None = Field(default=None, max_length=1000)
    chat_model: str | None = Field(default=None, max_length=255)
    embedding_model: str | None = Field(default=None, max_length=255)
