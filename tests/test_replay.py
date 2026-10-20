from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.service import RunManager
from src.db import create_history_schema
from src.models import AgentRequest, AgentRun


def test_replay_preserves_request_and_creates_a_new_independent_run(monkeypatch, tmp_path: Path) -> None:
    from src import history
    from app import service

    history_path = tmp_path / "history.sqlite"
    monkeypatch.setattr(history, "HISTORY_DB", history_path)
    create_history_schema(history_path)
    attempt_paths: list[Path] = []
    received_requests: list[AgentRequest] = []

    def new_attempt(run_id: str) -> Path:
        path = tmp_path / f"{run_id}.sqlite"
        attempt_paths.append(path)
        return path

    def fake_agent(request, *, settings, app_db, run_id, **_kwargs):
        received_requests.append(request)
        return AgentRun(
            run_id=run_id,
            timestamp="synthetic-test-time",
            mission_id=request.mission_id,
            customer_id=request.customer_id,
            authenticated=request.authenticated,
            allow_ticket_creation=request.allow_ticket_creation,
            model_name=settings.agent_model,
            prompt_version="test-prompt-v1",
            dataset_version="synthetic-v1",
            implementation_fingerprint="test-fingerprint",
            output="Synthetic test result",
            tool_calls=[],
            final_state={"tickets_before": 0, "tickets_after": 0, "ticket_count_for_request": 0},
            model_turns=1,
            latency_ms=1.0,
            input_tokens=10,
            output_tokens=5,
            estimated_cost_usd=None,
            resource_limits={"max_output_tokens_per_turn": 20},
        )

    monkeypatch.setattr(service, "new_attempt_database", new_attempt)
    monkeypatch.setattr(service, "run_customer_service_agent", fake_agent)
    manager = RunManager()
    original_request = AgentRequest(
        message="Please show my profile.",
        customer_id="CUST-100",
        authenticated=True,
        allow_ticket_creation=False,
        mission_id="profile_boundary",
    )
    settings = SimpleNamespace(agent_model="offline-test")

    first = manager.submit(original_request, settings)
    assert first.thread is not None
    first.thread.join(timeout=5)
    assert manager.get(first.run_id)["status"] == "completed"

    replay = manager.replay(first.run_id, settings)
    assert replay is not None and replay.thread is not None
    replay.thread.join(timeout=5)

    assert replay.run_id != first.run_id
    assert len(attempt_paths) == 2 and attempt_paths[0] != attempt_paths[1]
    assert len(received_requests) == 2
    assert received_requests[1].message == received_requests[0].message
    assert received_requests[1].customer_id == received_requests[0].customer_id
    assert received_requests[1].mission_id == received_requests[0].mission_id
    assert received_requests[1].request_id == replay.run_id
    assert len(manager.history()) == 2
