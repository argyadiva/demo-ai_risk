from __future__ import annotations

import json
from pathlib import Path

from src.config import PROJECT_ROOT
from src.db import CUSTOMERS, database_snapshot
from src.evidence import MISSION_IDS, rca_record_template
from src.models import AgentRequest, ToolContext
from src.setup_lab import setup
from src.tools import execute_tool


def test_three_customer_fixtures_are_explicitly_synthetic(app_db: Path) -> None:
    data = database_snapshot(app_db)
    assert len(data["customers"]) == 3
    assert all(customer["email"].endswith("@example.test") for customer in data["customers"])
    assert all("SIMULATED ADDRESS" in customer["shipping_address"] for customer in data["customers"])
    assert {customer["customer_id"] for customer in data["customers"]} == {"CUST-100", "CUST-200", "CUST-300"}


def test_customer_data_contract_names_visible_and_internal_fields() -> None:
    customer = CUSTOMERS[0]
    assert len(customer) == 7
    assert customer[2].endswith("@example.test")
    assert "Staff note:" in customer[5]
    assert customer[6].endswith("_demo")


def test_seed_setup_is_idempotent_and_does_not_touch_attempts(tmp_path: Path, monkeypatch) -> None:
    from src import setup_lab

    seed = tmp_path / "seed.sqlite"
    history = tmp_path / "history.sqlite"
    attempts_dir = tmp_path / "attempts"
    attempts_dir.mkdir()
    preserved = attempts_dir / "keep.txt"
    preserved.write_text("saved student evidence", encoding="utf-8")
    monkeypatch.setattr(setup_lab, "SEED_DB", seed)
    monkeypatch.setattr(setup_lab, "HISTORY_DB", history)
    # The CLI setup function uses these module-level paths. Only its seed can reset.
    setup_lab.setup(reset_seed=True)
    setup_lab.setup(reset_seed=False)
    assert preserved.read_text(encoding="utf-8") == "saved student evidence"
    assert seed.is_file() and history.is_file()


def test_mission_descriptions_expose_no_root_cause_or_answer_key() -> None:
    path = PROJECT_ROOT / "data" / "missions.json"
    missions = json.loads(path.read_text(encoding="utf-8"))
    assert {mission["mission_id"] for mission in missions} == MISSION_IDS
    text = path.read_text(encoding="utf-8").casefold()
    assert "root_cause" not in text
    assert "expected_fix" not in text


def test_api_key_is_not_part_of_agent_instructions() -> None:
    from src.agent import instructions_for_request

    prompt = instructions_for_request(AgentRequest("hello", customer_id="CUST-100", authenticated=True))
    assert "API_KEY" not in prompt
    assert "api key" not in prompt.casefold()


def test_anonymous_and_unknown_customer_profile_requests_are_rejected(app_db: Path) -> None:
    anonymous = ToolContext(
        request=AgentRequest("show the profile", customer_id="CUST-300", authenticated=False),
        app_db=app_db,
    )
    denied = execute_tool("get_customer_profile", {"customer_id": "CUST-100"}, anonymous)
    assert denied.result["error"] == "authentication_required"

    authenticated = ToolContext(
        request=AgentRequest("show the profile", customer_id="CUST-100", authenticated=True),
        app_db=app_db,
    )
    missing = execute_tool("get_customer_profile", {"customer_id": "CUST-999"}, authenticated)
    assert missing.result["error"] == "customer_not_found"


def test_ticket_failure_fixture_does_not_write_any_row(app_db: Path) -> None:
    from src.db import connect

    context = ToolContext(
        request=AgentRequest(
            "create one ticket", customer_id="CUST-100", authenticated=True,
            allow_ticket_creation=True, mission_id="truthful_actions",
            simulate_ticket_failure=True, request_id="NO-WRITE-FIXTURE",
        ),
        app_db=app_db,
    )
    failed = execute_tool(
        "create_support_ticket",
        {"summary": "Synthetic test issue", "priority": "high"},
        context,
    )
    assert failed.result == {"ok": False, "error": "storage_unavailable"}
    with connect(app_db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0


def test_rca_is_left_for_participants_to_complete() -> None:
    template = rca_record_template()
    assert "root_cause" in template and "observed_evidence" in template
    assert all(value == "" for value in template.values())
