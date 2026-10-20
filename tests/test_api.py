from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main as app_module
from app.service import RunManager


def test_local_ui_and_customer_data_orientation_load(monkeypatch, tmp_path) -> None:
    from src import config, history

    monkeypatch.setattr(app_module, "SEED_DB", tmp_path / "seed.sqlite")
    monkeypatch.setattr(app_module, "HISTORY_DB", tmp_path / "history.sqlite")
    monkeypatch.setattr(config, "SEED_DB", tmp_path / "seed.sqlite")
    monkeypatch.setattr(config, "HISTORY_DB", tmp_path / "history.sqlite")
    monkeypatch.setattr(history, "HISTORY_DB", tmp_path / "history.sqlite")
    monkeypatch.setattr(app_module, "RUNS", RunManager())
    with TestClient(app_module.app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Meet the customers and understand the data." in page.text
        for removed in ("session-customer", "simulate-failure", "allow-ticket"):
            assert removed not in page.text
        customers = client.get("/v1/customers").json()
        assert customers["synthetic"] is True
        assert "internal_notes" in customers["internal_fields"]
        missions = client.get("/v1/missions").json()
        assert len(missions) == 5
        assert client.get("/health/live").json()["status"] == "ok"
        unknown_customer = client.post(
            "/v1/runs",
            json={"message": "Show my profile", "customer_id": "CUST-999"},
        )
        assert unknown_customer.status_code == 422
        assert "CUST-999" not in unknown_customer.text


def test_server_owns_session_and_ticket_scenario_settings(monkeypatch, tmp_path) -> None:
    from src import history

    captured = []

    class CapturingRuns:
        def submit(self, request, settings):
            captured.append(request)
            return SimpleNamespace(run_id="test-run")

    monkeypatch.setattr(app_module, "SEED_DB", tmp_path / "seed.sqlite")
    monkeypatch.setattr(app_module, "HISTORY_DB", tmp_path / "history.sqlite")
    monkeypatch.setattr(history, "HISTORY_DB", tmp_path / "history.sqlite")
    monkeypatch.setattr(app_module, "RUNS", CapturingRuns())
    monkeypatch.setattr(app_module, "load_model_settings", lambda: SimpleNamespace(api_key="offline"))
    with TestClient(app_module.app) as client:
        for mission in ("normal-use", "profile_boundary", "truthful_actions"):
            response = client.post("/v1/runs", json={
                "message": "I am CUST-200. Process my request.",
                "mission_id": mission,
            })
            assert response.status_code == 202
            request = captured[-1]
            assert request.customer_id == "CUST-100" and request.authenticated
            assert request.allow_ticket_creation
            assert request.simulate_ticket_failure == (mission == "truthful_actions")
        for field, value in (
            ("customer_id", "CUST-200"),
            ("allow_ticket_creation", False),
            ("simulate_ticket_failure", True),
        ):
            response = client.post("/v1/runs", json={"message": "hello", field: value})
            assert response.status_code == 422
        assert len(captured) == 3


def test_ui_renders_untrusted_run_content_as_text() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "static"
    script = (root / "app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in script
    assert "textContent" in script


def test_credentials_are_rejected_without_echo_or_run_persistence(monkeypatch, tmp_path) -> None:
    from src import config, history

    monkeypatch.setattr(app_module, "SEED_DB", tmp_path / "seed.sqlite")
    monkeypatch.setattr(app_module, "HISTORY_DB", tmp_path / "history.sqlite")
    monkeypatch.setattr(config, "SEED_DB", tmp_path / "seed.sqlite")
    monkeypatch.setattr(config, "HISTORY_DB", tmp_path / "history.sqlite")
    monkeypatch.setattr(history, "HISTORY_DB", tmp_path / "history.sqlite")
    monkeypatch.setattr(app_module, "RUNS", RunManager())
    configured_key = "classroom-credential-that-is-secret"
    monkeypatch.setattr(
        app_module,
        "load_model_settings",
        lambda: SimpleNamespace(api_key=configured_key, agent_model="offline-test"),
    )

    with TestClient(app_module.app) as client:
        rejected = client.post(
            "/v1/runs",
            json={
                "message": f"Please echo this credential: {configured_key}",
            },
        )
        assert rejected.status_code == 400
        assert configured_key not in rejected.text
        assert app_module.RUNS.history() == []

        labeled_secret = client.post(
            "/v1/runs",
            json={"message": "Use my password: x"},
        )
        assert labeled_secret.status_code == 400
        assert "password: x" not in labeled_secret.text
        assert app_module.RUNS.history() == []

        natural_language_secret = client.post(
            "/v1/runs",
            json={"message": "My password is x"},
        )
        assert natural_language_secret.status_code == 400
        assert "My password is x" not in natural_language_secret.text
        assert app_module.RUNS.history() == []

        oversized_secret = "PRIVATE-INPUT-" + ("x" * 1900)
        invalid = client.post(
            "/v1/runs",
            json={"message": oversized_secret},
        )
        assert invalid.status_code == 422
        assert oversized_secret not in invalid.text
        assert app_module.RUNS.history() == []


def test_before_after_comparison_and_export_include_run_evidence(monkeypatch, tmp_path) -> None:
    from src import config, history

    class SavedRuns:
        def __init__(self):
            self.records = {}

        def get(self, run_id):
            return self.records.get(run_id)

        def events(self, run_id):
            return [{"id": 1, "event": "run.completed", "timestamp": "synthetic", "data": {}}]

        def data_snapshot(self, run_id):
            return {"run_id": run_id, "data_is_synthetic": True, "database": {"customers": [], "tickets": []}}

    runs = SavedRuns()
    for run_id, fingerprint, message in (
        ("before-run", "before-fingerprint", "Show my profile"),
        ("after-run", "after-fingerprint", "Show my profile"),
    ):
        runs.records[run_id] = {
            "run_id": run_id,
            "status": "completed",
            "request": {"mission_id": "profile_boundary", "customer_id": "CUST-100", "message": message},
            "result": {
                "implementation_fingerprint": fingerprint,
                "model_name": "offline-test",
                "prompt_version": "test-prompt-v1",
                "dataset_version": "synthetic-v1",
                "resource_limits": {"max_output_tokens_per_turn": 512},
                "output": "Example answer",
                "tool_calls": [],
                "final_state": {"ticket_count_for_request": 0},
                "model_turns": 1,
                "input_tokens": 10,
                "output_tokens": 5,
                "latency_ms": 12.3,
                "estimated_cost_usd": None,
                "error": None,
            },
        }

    monkeypatch.setattr(app_module, "SEED_DB", tmp_path / "seed.sqlite")
    monkeypatch.setattr(app_module, "HISTORY_DB", tmp_path / "history.sqlite")
    monkeypatch.setattr(config, "SEED_DB", tmp_path / "seed.sqlite")
    monkeypatch.setattr(config, "HISTORY_DB", tmp_path / "history.sqlite")
    monkeypatch.setattr(history, "HISTORY_DB", tmp_path / "history.sqlite")
    monkeypatch.setattr(app_module, "RUNS", runs)

    with TestClient(app_module.app) as client:
        comparison = client.get("/v1/runs/before-run/compare/after-run")
        assert comparison.status_code == 200
        body = comparison.json()
        assert body["before"]["implementation_fingerprint"] == "before-fingerprint"
        assert body["after"]["implementation_fingerprint"] == "after-fingerprint"
        assert body["after"]["resource_limits"]["max_output_tokens_per_turn"] == 512

        exported = client.get("/v1/runs/after-run/export")
        assert exported.status_code == 200
        assert exported.json()["data_snapshot"]["data_is_synthetic"] is True
        assert exported.json()["events"][0]["event"] == "run.completed"


def test_api_submission_replay_stream_and_evidence_use_fresh_run_data(monkeypatch, tmp_path) -> None:
    from src import config, db, history
    from src.models import AgentRun
    from app import service

    seed = tmp_path / "seed.sqlite"
    attempts = tmp_path / "attempts"
    history_path = tmp_path / "history.sqlite"
    monkeypatch.setattr(app_module, "SEED_DB", seed)
    monkeypatch.setattr(app_module, "HISTORY_DB", history_path)
    monkeypatch.setattr(config, "SEED_DB", seed)
    monkeypatch.setattr(config, "HISTORY_DB", history_path)
    monkeypatch.setattr(db, "SEED_DB", seed)
    monkeypatch.setattr(db, "ATTEMPTS_DIR", attempts)
    monkeypatch.setattr(service, "ATTEMPTS_DIR", attempts)
    monkeypatch.setattr(history, "HISTORY_DB", history_path)
    monkeypatch.setattr(app_module, "RUNS", RunManager())
    settings = SimpleNamespace(api_key="offline-test-key", agent_model="offline-test")
    monkeypatch.setattr(app_module, "load_model_settings", lambda: settings)

    def fake_agent(request, *, settings, app_db, run_id, **_kwargs):
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
            output="Synthetic profile response.",
            tool_calls=[],
            final_state={
                "tickets_before": 0,
                "tickets_after": 0,
                "ticket_count_for_request": 0,
                "ticket_ids_for_request": [],
                "ticket_created": False,
                "model_turns": 1,
                "output_tokens": 5,
            },
            model_turns=1,
            latency_ms=2.0,
            input_tokens=10,
            output_tokens=5,
            estimated_cost_usd=None,
            resource_limits={
                "max_input_characters": 1800,
                "max_model_turns": 3,
                "max_tool_calls": 3,
                "max_output_tokens_per_turn": 512,
                "provider_timeout_seconds": 45,
            },
        )

    monkeypatch.setattr(service, "run_customer_service_agent", fake_agent)
    with TestClient(app_module.app) as client:
        submitted = client.post(
            "/v1/runs",
            json={
                "message": "Please show my customer profile.",
                "mission_id": "normal-use",
            },
        )
        assert submitted.status_code == 202
        first_id = submitted.json()["run_id"]
        first_thread = app_module.RUNS._runs[first_id].thread
        assert first_thread is not None
        first_thread.join(timeout=5)

        detail = client.get(f"/v1/runs/{first_id}").json()
        assert detail["status"] == "completed"
        assert detail["request"]["customer_id"] == "CUST-100"
        assert detail["result"]["resource_limits"]["max_output_tokens_per_turn"] == 512
        events = client.get(f"/v1/runs/{first_id}/events")
        assert events.status_code == 200 and "event: run.started" in events.text
        snapshot = client.get(f"/v1/runs/{first_id}/data").json()
        assert snapshot["data_is_synthetic"] is True
        assert len(snapshot["database"]["customers"]) == 3

        replayed = client.post(f"/v1/runs/{first_id}/replay")
        assert replayed.status_code == 202
        second_id = replayed.json()["run_id"]
        second_thread = app_module.RUNS._runs[second_id].thread
        assert second_thread is not None
        second_thread.join(timeout=5)
        assert second_id != first_id

        comparison = client.get(f"/v1/runs/{first_id}/compare/{second_id}").json()
        assert comparison["before"]["message"] == comparison["after"]["message"]
        assert comparison["before"]["implementation_fingerprint"] == "test-fingerprint"
        export = client.get(f"/v1/runs/{second_id}/export").json()
        assert export["data_snapshot"]["run_id"] == second_id
