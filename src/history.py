from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.config import HISTORY_DB
from src.db import connect, json_text
from src.models import AgentRun, AgentRequest


def _time() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_run(run_id: str, request: AgentRequest) -> None:
    with connect(HISTORY_DB) as connection:
        connection.execute(
            "INSERT INTO runs(run_id, submitted_at, status, request_json) VALUES (?, ?, 'queued', ?)",
            (run_id, _time(), json_text(request.__dict__)),
        )
        connection.execute(
            "INSERT INTO run_events(run_id, event_id, event, timestamp, data_json) VALUES (?, 1, 'run.queued', ?, '{}')",
            (run_id, _time()),
        )


def append_event(run_id: str, event_id: int, event: str, data: dict[str, Any]) -> None:
    with connect(HISTORY_DB) as connection:
        connection.execute(
            "INSERT INTO run_events(run_id, event_id, event, timestamp, data_json) VALUES (?, ?, ?, ?, ?)",
            (run_id, event_id, event, _time(), json_text(data)),
        )


def update_status(run_id: str, status: str, *, error_category: str | None = None) -> None:
    with connect(HISTORY_DB) as connection:
        connection.execute(
            "UPDATE runs SET status = ?, error_category = ? WHERE run_id = ?",
            (status, error_category, run_id),
        )


def save_result(run: AgentRun) -> None:
    with connect(HISTORY_DB) as connection:
        connection.execute(
            "UPDATE runs SET status = ?, result_json = ?, error_category = ? WHERE run_id = ?",
            (
                "failed" if run.error else "completed",
                json_text(run.to_dict()),
                run.error,
                run.run_id,
            ),
        )


def get_run(run_id: str) -> dict[str, Any] | None:
    with connect(HISTORY_DB) as connection:
        row = connection.execute(
            "SELECT run_id, submitted_at, status, request_json, result_json, error_category FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    result = json.loads(row["result_json"]) if row["result_json"] else None
    if result is not None:
        # Preserve original recordings on disk; omit retired verdicts in read views.
        # Do not filter nested tool results: they are execution evidence.
        result.pop("checks", None)
        result.get("final_state", {}).pop("supported_operation_observed", None)
    return {
        "run_id": row["run_id"],
        "submitted_at": row["submitted_at"],
        "status": row["status"],
        "request": json.loads(row["request_json"]),
        "result": result,
        "error_category": row["error_category"],
    }


def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(int(limit), 100))
    with connect(HISTORY_DB) as connection:
        rows = connection.execute(
            "SELECT run_id, submitted_at, status, request_json, result_json, error_category FROM runs ORDER BY submitted_at DESC LIMIT ?",
            (bounded_limit,),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        request = json.loads(row["request_json"])
        result.append({
            "run_id": row["run_id"],
            "submitted_at": row["submitted_at"],
            "status": row["status"],
            "mission_id": request["mission_id"],
            "customer_id": request["customer_id"],
            "message": request["message"],
            "error_category": row["error_category"],
        })
    return result


def list_events(run_id: str, after_event_id: int = 0) -> list[dict[str, Any]]:
    with connect(HISTORY_DB) as connection:
        rows = connection.execute(
            "SELECT event_id, event, timestamp, data_json FROM run_events WHERE run_id = ? AND event_id > ? ORDER BY event_id",
            (run_id, after_event_id),
        ).fetchall()
    events = []
    for row in rows:
        data = json.loads(row["data_json"])
        if row["event"] in {"run.completed", "result.saved"}:
            data.pop("checks", None)
        events.append({"id": row["event_id"], "event": row["event"], "timestamp": row["timestamp"], "data": data})
    return events
