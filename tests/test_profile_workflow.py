from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src import agent
from src.models import AgentRequest, ToolCallRecord


@pytest.mark.parametrize("mission", ["profile_boundary", "normal-use", "resource_budget", "truthful_actions", "data_minimization", "ticket_idempotency"])
def test_model_selects_tools_and_actual_results_are_preserved(app_db, mission):
    requests = []
    responses = iter([
        {
            "output": [{"type": "function_call", "name": "get_customer_profile",
                        "arguments": json.dumps({"customer_id": "CUST-100"}), "call_id": "profile"}],
            "usage": {"input_tokens": 10, "output_tokens": 10},
        },
        {"output": [], "output_text": "Model-generated profile answer", "usage": {}},
    ])

    def create(**kwargs):
        requests.append(kwargs)
        return next(responses)

    events = []
    settings = SimpleNamespace(
        agent_model="offline-test", hard_max_model_turns=3, hard_max_tool_calls=3,
        hard_max_output_tokens_per_turn=512, input_cost_per_1m=None, output_cost_per_1m=None,
    )
    run = agent.run_customer_service_agent(
        AgentRequest("Show my profile", customer_id="CUST-100", authenticated=True, mission_id=mission),
        settings=settings, app_db=app_db,
        client=SimpleNamespace(responses=SimpleNamespace(create=create)),
        event_sink=lambda name, data: events.append((name, data)),
    )
    expected = ["auto", "auto"]
    assert [call["tool_choice"] for call in requests] == expected
    assert [data["tool_choice"] for name, data in events if name == "model.started"] == expected
    assert run.error is None
    assert run.output == "Model-generated profile answer"
    assert run.tool_calls[0].arguments == {"customer_id": "CUST-100"}
    assert all(call["max_output_tokens"] <= 512 for call in requests)


def test_injected_lookup_preserves_session_and_a_repaired_tool_denial(monkeypatch, app_db):
    captured = []

    def repaired_tool(name, arguments, context):
        captured.append((arguments, context.request.customer_id))
        return ToolCallRecord(
            name=name, arguments=arguments, result={"ok": False, "error": "authorization_failed"},
            authorized=False, status="blocked", latency_ms=0,
        )

    calls = 0

    def create(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"output": [{"type": "function_call", "name": "get_customer_profile",
                                "arguments": '{"customer_id":"CUST-200"}', "call_id": "foreign"}], "usage": {}}
        tool_output = json.loads(kwargs["input"][-1]["output"])
        assert tool_output == {"ok": False, "error": "authorization_failed"}
        return {"output": [], "output_text": "The lookup was denied.", "usage": {}}

    monkeypatch.setattr(agent, "execute_tool", repaired_tool)
    run = agent.run_customer_service_agent(
        AgentRequest("Show CUST-200", customer_id="CUST-100", authenticated=True, mission_id="profile_boundary"),
        settings=SimpleNamespace(
            agent_model="offline-test", hard_max_model_turns=3, hard_max_tool_calls=3,
            hard_max_output_tokens_per_turn=512, input_cost_per_1m=None, output_cost_per_1m=None,
        ),
        app_db=app_db, client=SimpleNamespace(responses=SimpleNamespace(create=create)),
    )
    assert captured == [({"customer_id": "CUST-200"}, "CUST-100")]
    assert run.tool_calls[0].result["error"] == "authorization_failed"
    assert run.output == "The lookup was denied."
