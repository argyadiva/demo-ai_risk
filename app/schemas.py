from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


MissionId = Literal[
    "normal-use", "profile_boundary", "resource_budget",
    "data_minimization", "truthful_actions", "ticket_idempotency",
]


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=1800)
    mission_id: MissionId = "normal-use"


class RunAccepted(BaseModel):
    run_id: str
    status: Literal["queued"]
    events_url: str
