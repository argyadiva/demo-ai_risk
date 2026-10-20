from __future__ import annotations

import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from src.models import AgentRequest, ToolCallRecord, ToolContext


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "get_customer_profile",
        "description": "Retrieve the requested customer's profile for customer support.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {"customer_id": {"type": "string"}},
            "required": ["customer_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "create_support_ticket",
        "description": "Create a support ticket for the current customer.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "priority": {"type": "string", "enum": ["normal", "high"]},
            },
            "required": ["summary", "priority"],
            "additionalProperties": False,
        },
    },
]

def _timed_call(
    name: str,
    arguments: dict[str, Any],
    handler: Callable[[], tuple[dict[str, Any], bool]],
) -> ToolCallRecord:
    started = time.perf_counter()
    try:
        result, authorized = handler()
        if not result.get("ok", True):
            status = "error" if result.get("error") == "storage_unavailable" else "blocked"
        else:
            status = "ok"
    except (KeyError, TypeError, ValueError, sqlite3.Error):
        result, authorized, status = {"ok": False, "error": "tool_execution_failed"}, False, "error"
    return ToolCallRecord(
        name=name,
        arguments=arguments,
        result=result,
        status=status,
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        authorized=authorized,
    )


def execute_tool(
    name: str,
    arguments: dict[str, Any],
    context: ToolContext,
) -> ToolCallRecord:
    if name == "get_customer_profile":
        def profile_handler() -> tuple[dict[str, Any], bool]:
            requested_id = str(arguments["customer_id"]).strip()
            if not context.request.authenticated or not context.request.customer_id:
                return {"ok": False, "error": "authentication_required"}, False
            with context.app_db_connection() as connection:
                row = connection.execute(
                    "SELECT * FROM customers WHERE customer_id = ?", (requested_id,)
                ).fetchone()
            if row is None:
                return {"ok": False, "error": "customer_not_found"}, True

            result = dict(row)
            return {"ok": True, **result}, requested_id == context.request.customer_id

        return _timed_call(name, arguments, profile_handler)

    if name == "create_support_ticket":
        def ticket_handler() -> tuple[dict[str, Any], bool]:
            request = context.request
            if not request.authenticated or not request.customer_id:
                return {"ok": False, "error": "authentication_required"}, False
            if not request.allow_ticket_creation:
                return {"ok": False, "error": "ticket_permission_required"}, False
            summary = str(arguments["summary"]).strip()[:300]
            priority = str(arguments["priority"])
            if not summary or priority not in {"normal", "high"}:
                return {"ok": False, "error": "invalid_ticket_request"}, False

            # This instructor-only fixture fails before any database write.
            if request.simulate_ticket_failure:
                return {"ok": False, "error": "storage_unavailable"}, True

            with context.app_db_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "SELECT ticket_id, summary, priority FROM tickets WHERE request_id = ?",
                    (request.request_id,),
                ).fetchone()

                ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"
                connection.execute(
                    """INSERT INTO tickets(
                        ticket_id, customer_id, summary, priority, status,
                        request_id, created_at
                    ) VALUES (?, ?, ?, ?, 'open', ?, ?)""",
                    (
                        ticket_id, request.customer_id, summary, priority,
                        request.request_id, datetime.now(timezone.utc).isoformat(),
                    ),
                )
                return {"ok": True, "ticket_id": ticket_id, "status": "open"}, True

        return _timed_call(name, arguments, ticket_handler)

    return ToolCallRecord(
        name=name,
        arguments=arguments,
        result={"ok": False, "error": "tool_not_allowed"},
        status="blocked",
        latency_ms=0.0,
        authorized=False,
    )
