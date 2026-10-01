"""Colleague picker schemas."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ColleagueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str
