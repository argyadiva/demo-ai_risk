from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=1800)


class RunAccepted(BaseModel):
    run_id: str
    status: Literal["queued"]
    events_url: str
