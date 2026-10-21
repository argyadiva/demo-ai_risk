import json
from types import SimpleNamespace

from src.agent import instructions_for_request, run_customer_service_agent
from src.db import connect
from src.models import AgentRequest, ToolContext
from src.tools import execute_tool


class Client:
    def __init__(self, responses):
        self.pending = iter(responses)
        self.calls = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.pending)


def test_own_profile_uses_real_tool_result_and_keeps_user_text_in_user_input(app_db, settings):
    client = Client([
        {"output": [{"type": "function_call", "name": "get_customer_profile",
                     "arguments": '{"customer_id":"CUST-100"}', "call_id": "p1"}],
         "usage": {"input_tokens": 11, "output_tokens": 4}},
        {"output": [], "output_text": "Your profile is available.",
         "usage": {"input_tokens": 15, "output_tokens": 8}},
    ])
    events = []
    request = AgentRequest("Show my customer profile.", customer_id="CUST-100", authenticated=True)
    run = run_customer_service_agent(
        request, settings=settings, app_db=app_db, client=client,
        event_sink=lambda name, data: events.append((name, data)),
    )
    assert run.error is None
    assert run.tool_calls[0].result["customer_id"] == "CUST-100"
    assert run.input_tokens == 26 and run.output_tokens == 12
    assert client.calls[0]["instructions"] == instructions_for_request(request)
    assert request.message not in client.calls[0]["instructions"]
    user_item = next(item for item in client.calls[0]["input"] if item.get("role") == "user")
    assert json.loads(user_item["content"])["message"] == request.message
    assert all(call["tool_choice"] == "auto" for call in client.calls)
    assert all(call["max_output_tokens"] <= 512 for call in client.calls)
    assert {item["name"] for item in client.calls[0]["tools"]} == {
        "get_customer_profile", "create_support_ticket"
    }
    assert any(name == "database.observed" for name, _data in events)


def test_homework_uses_the_same_agent_path_without_command_routing(app_db, settings):
    # The canned output verifies wiring only, not whether a live prompt will refuse.
    request = AgentRequest("Explain the Pythagorean theorem.", customer_id="CUST-100", authenticated=True)
    client = Client([{"output": [], "output_text": "Offline response.", "usage": {}}])
    run = run_customer_service_agent(request, settings=settings, app_db=app_db, client=client)
    assert run.error is None and run.model_turns == 1
    assert client.calls[0]["instructions"] == instructions_for_request(request)
    assert len(client.calls[0]["tools"]) == 2


def test_ticket_tool_still_creates_a_normal_ticket(app_db):
    context = ToolContext(
        request=AgentRequest("Create a ticket", customer_id="CUST-100", authenticated=True,
                             allow_ticket_creation=True, request_id="ticket-smoke"),
        app_db=app_db,
    )
    call = execute_tool("create_support_ticket", {"summary": "Damaged test parcel", "priority": "normal"}, context)
    assert call.result["ok"]
    with connect(app_db) as connection:
        row = connection.execute("SELECT * FROM tickets WHERE ticket_id=?", (call.result["ticket_id"],)).fetchone()
    assert row["customer_id"] == "CUST-100" and row["request_id"] == "ticket-smoke"


def test_agent_normalizes_request_id_before_tool_execution(app_db, settings):
    client = Client([
        {"output": [{"type": "function_call", "name": "create_support_ticket",
                     "arguments": '{"summary":"Test issue","priority":"normal"}', "call_id": "t1"}], "usage": {}},
        {"output": [], "output_text": "Recorded.", "usage": {}},
    ])
    request = AgentRequest("Create a support ticket", customer_id="CUST-100",
                           authenticated=True, allow_ticket_creation=True)
    run = run_customer_service_agent(request, settings=settings, app_db=app_db, client=client)
    assert run.final_state["ticket_count_for_request"] == 1
    with connect(app_db) as connection:
        row = connection.execute("SELECT request_id FROM tickets").fetchone()
    assert row["request_id"] == run.run_id


def test_outer_resource_limits_bound_repeated_tool_proposals(app_db, settings):
    tool = {"output": [{"type": "function_call", "name": "get_customer_profile",
                       "arguments": '{"customer_id":"CUST-100"}', "call_id": "p"}], "usage": {}}
    client = Client([tool] * 10)
    run = run_customer_service_agent(
        AgentRequest("Show my profile", customer_id="CUST-100", authenticated=True),
        settings=settings, app_db=app_db, client=client,
    )
    assert run.model_turns <= 3 and len(run.tool_calls) <= 3
    assert all(call["max_output_tokens"] <= 512 for call in client.calls)


def test_provider_errors_do_not_echo_sensitive_exception_text(app_db, settings):
    def fail(**kwargs):
        raise RuntimeError("private-provider-context")
    client = SimpleNamespace(responses=SimpleNamespace(create=fail))
    run = run_customer_service_agent(AgentRequest("Hello"), settings=settings, app_db=app_db, client=client)
    assert run.error is not None
    assert "private-provider-context" not in run.output
