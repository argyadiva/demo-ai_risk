from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field, fields
from typing import Any


@dataclass(frozen=True)
class AgentRequest:
    message: str
    customer_id: str | None = None
    authenticated: bool = False
    allow_ticket_creation: bool = False
    request_id: str = ""

    @classmethod
    def from_saved(cls, payload: dict[str, Any]) -> AgentRequest:
        """Read old saved requests without reviving removed runtime settings."""
        return cls(**{
            item.name: payload[item.name]
            for item in fields(cls)
            if item.name in payload
        })


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    status: str
    latency_ms: float
    authorized: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentRun:
    run_id: str
    timestamp: str
    customer_id: str | None
    authenticated: bool
    allow_ticket_creation: bool
    model_name: str
    prompt_version: str
    dataset_version: str
    implementation_fingerprint: str
    output: str
    tool_calls: list[ToolCallRecord]
    final_state: dict[str, Any]
    model_turns: int
    latency_ms: float
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None
    resource_limits: dict[str, int | float]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolContext:
    request: AgentRequest
    app_db: Any
    tickets_before: int = 0
    successful_ticket_ids: list[str] = field(default_factory=list)

    def app_db_connection(self) -> AbstractContextManager[Any]:
        from src.db import connect

        return connect(self.app_db)
