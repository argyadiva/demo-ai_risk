from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.agent import run_customer_service_agent
from src.config import ATTEMPTS_DIR, HISTORY_DB
from src.db import database_snapshot, new_attempt_database
from src.history import append_event, create_run, save_result, update_status
from src.models import AgentRequest


TERMINAL_STATES = {"completed", "failed", "cancelled"}


@dataclass
class ManagedRun:
    run_id: str
    request: AgentRequest
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None


class RunManager:
    def __init__(self) -> None:
        self._runs: dict[str, ManagedRun] = {}
        self._lock = threading.RLock()

    def submit(self, request: AgentRequest, settings: Any, *, run_id: str | None = None) -> ManagedRun:
        selected_id = run_id or str(uuid.uuid4())
        stored_request = replace(request, request_id=selected_id)
        managed = ManagedRun(run_id=selected_id, request=stored_request)
        create_run(selected_id, stored_request)
        with self._lock:
            self._runs[selected_id] = managed
        managed.thread = threading.Thread(
            target=self._execute, args=(managed, settings),
            name=f"m15-run-{selected_id[:8]}", daemon=True,
        )
        managed.thread.start()
        return managed

    def _execute(self, managed: ManagedRun, settings: Any) -> None:
        state = {"event_id": 1, "terminal": False}
        event_lock = threading.RLock()

        def emit(event: str, data: dict[str, Any]) -> None:
            with event_lock:
                state["event_id"] += 1
                append_event(managed.run_id, state["event_id"], event, data)
                if event == "run.completed":
                    state["terminal"] = True

        try:
            update_status(managed.run_id, "running")
            emit("run.started", {"status": "running", "mission_id": managed.request.mission_id})
            app_db = new_attempt_database(managed.run_id)
            run = run_customer_service_agent(
                managed.request,
                settings=settings,
                app_db=app_db,
                event_sink=emit,
                cancel_check=managed.cancel_event.is_set,
                run_id=managed.run_id,
            )
            save_result(run)
            update_status(managed.run_id, "failed" if run.error else "completed", error_category=run.error)
            emit("result.saved", {"status": "failed" if run.error else "completed"})
        except Exception:
            update_status(managed.run_id, "failed", error_category="run_setup_failed")
            emit("run.failed", {"status": "failed", "error": "run_setup_failed"})

    def get(self, run_id: str) -> dict[str, Any] | None:
        from src.history import get_run

        return get_run(run_id)

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        from src.history import list_runs

        return list_runs(limit)

    def events(self, run_id: str, after_event_id: int = 0) -> list[dict[str, Any]]:
        from src.history import list_events

        return list_events(run_id, after_event_id)

    def cancel(self, run_id: str) -> tuple[bool, str] | None:
        with self._lock:
            managed = self._runs.get(run_id)
            if managed is None:
                return None
            record = self.get(run_id)
            if not record or record["status"] in TERMINAL_STATES:
                return False, record["status"] if record else "unknown"
            managed.cancel_event.set()
            return True, "cancellation_requested"

    def data_snapshot(self, run_id: str) -> dict[str, Any] | None:
        try:
            parsed = uuid.UUID(run_id)
        except (ValueError, TypeError, AttributeError):
            return None
        record = self.get(str(parsed))
        if record is None or not record.get("result"):
            return None
        path = ATTEMPTS_DIR / f"{parsed}.sqlite"
        if not path.is_file() or path.parent.resolve() != ATTEMPTS_DIR.resolve():
            return None
        result = record["result"]
        before = int(result.get("final_state", {}).get("tickets_before", 0))
        after = int(result.get("final_state", {}).get("tickets_after", 0))
        snapshot = database_snapshot(path)
        return {
            "run_id": run_id,
            "database": snapshot,
            "ticket_change_count": after - before,
            "ticket_ids_for_request": result.get("final_state", {}).get("ticket_ids_for_request", []),
            "data_is_synthetic": True,
        }

    def replay(self, run_id: str, settings: Any) -> ManagedRun | None:
        old = self.get(run_id)
        if old is None:
            return None
        request_data = old["request"]
        request_data["request_id"] = ""
        request = AgentRequest(**request_data)
        return self.submit(request, settings)
