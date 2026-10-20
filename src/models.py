from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


MissionId = Literal["profile_boundary", "resource_budget", "data_minimization", "truthful_actions", "ticket_idempotency"]
IdentityId = Literal["CUST-100", "CUST-200", "CUST-300"]


@dataclass(frozen=True)
class AgentRequest:
    message: str
    customer_id: str | None = None
    authenticated: bool = False
    allow_ticket_creation: bool = False
    mission_id: str = "normal-use"
    simulate_ticket_failure: bool = False
    request_id: str = ""


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
    mission_id: str
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
