import json
from dataclasses import fields

import pytest
from fastapi.testclient import TestClient

from app import main as api
from app import service
from app.schemas import RunCreate
from app.service import RunManager
from src import agent, config, db, history
from src.models import AgentRequest


@pytest.fixture
def browser(monkeypatch, tmp_path, settings):
    seed = tmp_path / "seed.sqlite"
    saved = tmp_path / "history.sqlite"
    attempts = tmp_path / "attempts"
    for module in (api, config, db):
        monkeypatch.setattr(module, "SEED_DB", seed)
    for module in (api, config, history):
        monkeypatch.setattr(module, "HISTORY_DB", saved)
    for module in (config, db, service):
        monkeypatch.setattr(module, "ATTEMPTS_DIR", attempts)
    monkeypatch.setattr(api, "load_model_settings", lambda: settings)
    monkeypatch.setattr(api, "RUNS", RunManager())

    class ProfileClient:
        def __init__(self):
            self.responses = self
            self.turn = 0

        def create(self, **kwargs):
            self.turn += 1
            if self.turn == 1:
                return {"output": [{
                    "type": "function_call", "name": "get_customer_profile",
                    "arguments": '{"customer_id":"CUST-100"}', "call_id": "p",
                }], "usage": {"input_tokens": 10, "output_tokens": 4}}
            return {"output": [], "output_text": "Maya's synthetic profile.", "usage": {}}

    monkeypatch.setattr(agent, "build_client", lambda _settings: ProfileClient())
    with TestClient(api.app) as client:
        yield client


def finish(run_id):
    worker = api.RUNS._runs[run_id].thread
    worker.join(timeout=10)
    assert not worker.is_alive()


def test_chat_page_and_api_are_one_agent_with_message_only_input(browser):
    page = browser.get("/")
    assert page.status_code == 200
    assert "Support chat" in page.text and "Trace inspector" in page.text
    assert "mission-list" not in page.text and "next-hint" not in page.text
    assert set(RunCreate.model_fields) == {"message"}
    assert browser.get("/v1/missions").status_code == 404
    assert browser.get("/v1/customers").json()["current_customer"]["customer_id"] == "CUST-100"


@pytest.mark.parametrize("field,value", [
    ("customer_id", "CUST-200"), ("authenticated", False),
    ("allow_ticket_creation", False), ("mission_id", "profile_boundary"),
    ("simulate_ticket_failure", True),
])
def test_client_cannot_supply_identity_permissions_or_removed_scenarios(browser, field, value):
    response = browser.post("/v1/runs", json={"message": "Show my profile", field: value})
    assert response.status_code == 422
    assert api.RUNS.history() == []


def test_real_agent_submission_stream_replay_comparison_and_export(browser):
    first = browser.post("/v1/runs", json={"message": "Show my profile"})
    assert first.status_code == 202
    before_id = first.json()["run_id"]
    finish(before_id)
    detail = browser.get(f"/v1/runs/{before_id}").json()
    assert detail["status"] == "completed"
    assert detail["request"]["customer_id"] == "CUST-100"
    assert "mission_id" not in detail["request"] and "mission_id" not in detail["result"]
    assert detail["result"]["tool_calls"][0]["result"]["customer_id"] == "CUST-100"
    stream = browser.get(f"/v1/runs/{before_id}/events")
    assert "event: tool.completed" in stream.text
    assert browser.get(f"/v1/runs/{before_id}/data").json()["data_is_synthetic"]

    after = browser.post(f"/v1/runs/{before_id}/replay")
    after_id = after.json()["run_id"]
    finish(after_id)
    assert before_id != after_id
    comparison = browser.get(f"/v1/runs/{before_id}/compare/{after_id}").json()
    assert comparison["before"]["message"] == comparison["after"]["message"]
    assert "mission_id" not in comparison["before"]
    export = browser.get(f"/v1/runs/{after_id}/export").json()
    assert export["data_snapshot"]["run_id"] == after_id
    assert len(browser.get("/v1/runs").json()) == 2


def test_legacy_history_replays_without_restoring_old_settings_or_rewriting_storage(browser):
    before = browser.post("/v1/runs", json={"message": "Show my profile"}).json()["run_id"]
    finish(before)
    with db.connect(history.HISTORY_DB) as connection:
        row = connection.execute("SELECT request_json,result_json FROM runs WHERE run_id=?", (before,)).fetchone()
        old_request = json.loads(row["request_json"])
        old_request.update(mission_id="truthful_actions", simulate_ticket_failure=True)
        old_result = json.loads(row["result_json"])
        old_result.update(mission_id="truthful_actions", checks={"old": "retired"})
        request_json = json.dumps(old_request)
        result_json = json.dumps(old_result)
        connection.execute("UPDATE runs SET request_json=?,result_json=? WHERE run_id=?",
                           (request_json, result_json, before))
    record = browser.get(f"/v1/runs/{before}").json()
    assert set(record["request"]) == {item.name for item in fields(AgentRequest)}
    assert "checks" not in record["result"] and "mission_id" not in record["result"]
    replay_id = browser.post(f"/v1/runs/{before}/replay").json()["run_id"]
    finish(replay_id)
    replay = browser.get(f"/v1/runs/{replay_id}").json()
    assert replay["status"] == "completed" and "simulate_ticket_failure" not in replay["request"]
    with db.connect(history.HISTORY_DB) as connection:
        saved = connection.execute("SELECT request_json,result_json FROM runs WHERE run_id=?", (before,)).fetchone()
    assert saved["request_json"] == request_json and saved["result_json"] == result_json


def test_credentials_and_invalid_input_are_not_echoed_or_persisted(browser):
    for message in ("offline-test-credential", "My password is private-value"):
        response = browser.post("/v1/runs", json={"message": message})
        assert response.status_code == 400 and message not in response.text
    oversized = "private-input-" + "x" * 1900
    response = browser.post("/v1/runs", json={"message": oversized})
    assert response.status_code == 422 and oversized not in response.text
    assert browser.get("/v1/runs").json() == []


def test_setup_preserves_saved_evidence(monkeypatch, tmp_path):
    from src import setup_lab
    seed = tmp_path / "seed.sqlite"
    saved = tmp_path / "history.sqlite"
    evidence = tmp_path / "attempts" / "keep.txt"
    evidence.parent.mkdir()
    evidence.write_text("saved evidence")
    monkeypatch.setattr(setup_lab, "SEED_DB", seed)
    monkeypatch.setattr(setup_lab, "HISTORY_DB", saved)
    setup_lab.setup(reset_seed=True)
    setup_lab.setup(reset_seed=False)
    assert evidence.read_text() == "saved evidence"


def test_browser_script_preserves_text_rendering_and_evidence_surfaces():
    script = (config.PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in script
    assert "JSON.stringify({ message })" in script
    for element in ("trace-list", "data-state", "history-list", "comparison-result"):
        assert element in script
