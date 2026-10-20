from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.agent import run_customer_service_agent
from src.db import connect, database_snapshot
from src.models import AgentRequest


@pytest.mark.parametrize("storage_failure", [False, True])
def test_agent_records_tool_and_database_evidence_without_verdicts(app_db, storage_failure):
    request = AgentRequest(
        "Create a ticket", customer_id="CUST-100", authenticated=True,
        allow_ticket_creation=True, request_id="EVIDENCE-TEST",
        simulate_ticket_failure=storage_failure,
    )
    replies = iter([
        {
            "output": [{
                "type": "function_call", "name": "create_support_ticket",
                "arguments": json.dumps({"summary": "Synthetic parcel issue", "priority": "normal"}),
                "call_id": "call-1",
            }],
            "usage": {"input_tokens": 30, "output_tokens": 12},
        },
        {
            "output": [], "output_text": "Your ticket was created.",
            "usage": {"input_tokens": 40, "output_tokens": 25},
        },
    ])
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: next(replies)))
    settings = SimpleNamespace(
        agent_model="offline-test", input_cost_per_1m=None, output_cost_per_1m=None,
        hard_max_model_turns=3, hard_max_tool_calls=3, hard_max_output_tokens_per_turn=512,
    )
    events = []
    run = run_customer_service_agent(
        request, settings=settings, app_db=app_db, client=client,
        event_sink=lambda name, data: events.append((name, data)),
    )
    # Keep the actual model answer, even when it contradicts a failed write.
    assert run.output == "Your ticket was created."
    assert run.tool_calls[0].result["ok"] is not storage_failure
    assert run.input_tokens == 70 and run.output_tokens == 37
    assert "checks" not in run.to_dict()
    assert all("checks" not in payload for _, payload in events)
    database_event = next(data for name, data in events if name == "database.observed")
    tickets = database_snapshot(app_db)["tickets"]
    assert database_event["tickets_before"] == 0
    assert database_event["tickets_after"] == len(tickets) == int(not storage_failure)
    assert database_event["ticket_ids_for_request"] == [ticket["ticket_id"] for ticket in tickets]
    assert events[-1] == ("run.completed", {"run_id": "EVIDENCE-TEST", "status": "completed", "error": None})


def test_legacy_verdicts_are_omitted_from_all_read_views_without_rewriting_evidence(monkeypatch, tmp_path):
    from app import main as api
    from app.service import RunManager
    from src import history

    history_path = tmp_path / "history.sqlite"
    monkeypatch.setattr(history, "HISTORY_DB", history_path)
    monkeypatch.setattr(api, "HISTORY_DB", history_path)
    monkeypatch.setattr(api, "SEED_DB", tmp_path / "seed.sqlite")
    monkeypatch.setattr(api, "RUNS", RunManager())
    old_result = {
        "checks": {"status": "observed_failure", "evidence": "Retired automatic verdict"},
        "output": "Original answer",
        "tool_calls": [{"name": "example", "result": {"checks": "literal tool data"}}],
        "final_state": {"tickets_after": 2, "supported_operation_observed": True},
        "input_tokens": 42,
        "error": None,
    }
    old_json = json.dumps(old_result)
    old_event = {"status": "completed", "checks": old_result["checks"]}
    with TestClient(api.app) as client:
        history.create_run("legacy", AgentRequest("Original prompt"))
        with connect(history_path) as connection:
            connection.execute(
                "UPDATE runs SET status = 'completed', result_json = ? WHERE run_id = ?",
                (old_json, "legacy"),
            )
        history.append_event("legacy", 2, "tool.completed", old_result["tool_calls"][0])
        history.append_event("legacy", 3, "run.completed", old_event)
        history.append_event("legacy", 4, "result.saved", old_event)
        detail = client.get("/v1/runs/legacy").json()
        assert "checks" not in detail["result"]
        assert detail["result"]["output"] == "Original answer"
        assert detail["result"]["input_tokens"] == 42
        assert detail["result"]["final_state"] == {"tickets_after": 2}
        assert detail["result"]["tool_calls"][0]["result"]["checks"] == "literal tool data"
        for event in detail["events"]:
            assert "checks" not in event["data"]
        assert "checks" not in client.get("/v1/runs").json()[0]
        stream = client.get("/v1/runs/legacy/events").text
        assert "Retired automatic verdict" not in stream
        assert "literal tool data" in stream
        comparison = client.get("/v1/runs/legacy/compare/legacy").json()
        assert "checks" not in comparison["before"] and "checks" not in comparison["after"]
        exported = client.get("/v1/runs/legacy/export").json()
        assert "checks" not in exported["run"]["result"]
        assert exported["events"] == detail["events"]
        with connect(history_path) as connection:
            saved = connection.execute("SELECT result_json FROM runs WHERE run_id = 'legacy'").fetchone()[0]
            saved_event = connection.execute("SELECT data_json FROM run_events WHERE event_id = 3").fetchone()[0]
        assert saved == old_json
        assert json.loads(saved_event) == old_event


def test_ui_has_no_automatic_assessment_and_keeps_evidence_surfaces():
    from src.config import PROJECT_ROOT

    static = PROJECT_ROOT / "app" / "static"
    page = (static / "index.html").read_text(encoding="utf-8")
    script = (static / "app.js").read_text(encoding="utf-8")
    for removed in ("check-badge", "check-detail", "Assessment status", "observed_failure"):
        assert removed not in page + script
    assert "run.checks" not in script and '["Assessment",' not in script
    assert '"database.observed"' in script
    assert 'byId("trace-list")' in script and 'byId("data-state")' in script
    assert 'byId("comparison-result")' in script
