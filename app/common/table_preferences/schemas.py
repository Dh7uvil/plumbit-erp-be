"""Request and response schemas for user table column preferences."""

from pydantic import BaseModel, ConfigDict, Field


class TablePreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visible_columns: list[str] = Field(min_length=1, max_length=50)
    column_order: list[str] = Field(min_length=1, max_length=50)


class TablePreferenceResponse(BaseModel):
    table_key: str
    visible_columns: list[str]
    column_order: list[str]
    is_default: bool
