from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app.schemas import RunAccepted, RunCreate
from app.service import RunManager
from src.config import PROJECT_ROOT
from src.db import CUSTOMERS, create_history_schema, seed_database
from src.history import get_run
from src.config import HISTORY_DB, SEED_DB
from src.config import load_model_settings
from src.models import AgentRequest
from src.evidence import rca_record_template


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    seed_database(SEED_DB)
    create_history_schema(HISTORY_DB)
    yield


app = FastAPI(
    title="Module 16: Fix This Agent",
    description="One local synthetic customer-support agent with execution evidence.",
    version="1.0.0",
    lifespan=lifespan,
)
RUNS = RunManager()
STATIC = PROJECT_ROOT / "app" / "static"
SECRET_PATTERN = re.compile(
    r"(?ix)(?:"
    r"\bsk-[A-Za-z0-9_-]{12,}\b"
    r"|\b(?:api[_ -]?key|access[_ -]?token|password|passwd|secret|token)\b"
    r"\s*[:=]\s*(?:bearer\s+)?[^\s,;]{1,}"
    r"|\b(?:my\s+)?(?:password|passphrase|secret|token)\s+is\s+[^\s,;]+"
    r"|\b(?:api[_ -]?key|access[_ -]?token)\s+is\s+[^\s,;]+"
    r"|\bbearer\s+[A-Za-z0-9._~+/-]{1,}=*"
    r")"
)


@app.exception_handler(RequestValidationError)
async def safe_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Pydantic's default response can echo the rejected input value. Preserve
    # useful location/message/type information, but never serialize that value.
    detail = [
        {
            "loc": list(error.get("loc", ())),
            "msg": str(error.get("msg", "Invalid request")),
            "type": str(error.get("type", "value_error")),
        }
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detail})


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/static/{filename}", include_in_schema=False)
async def static_file(filename: str) -> FileResponse:
    if filename not in {"app.js", "styles.css"}:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(STATIC / filename)


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready() -> dict[str, object]:
    try:
        settings = load_model_settings()
        configured = bool(settings.api_key and settings.agent_model)
        model = settings.agent_model if configured else None
    except RuntimeError:
        configured, model = False, None
    return {"status": "ready", "model_configured": configured, "model": model, "data": "synthetic"}


@app.get("/version")
async def version() -> dict[str, str]:
    return {"app": app.version, "dataset": "northstar-synthetic-2026-10-20"}


@app.get("/v1/customers")
async def customers() -> dict[str, object]:
    return {
        "synthetic": True,
        "current_customer": {"customer_id": "CUST-100", "display_name": "Maya Example"},
        "customers": [
            {"customer_id": row[0], "display_name": row[1]}
            for row in CUSTOMERS
        ],
        "visible_fields": ["customer_id", "display_name", "email", "phone", "shipping_address"],
        "internal_fields": ["internal_notes", "review_flag"],
        "tickets": ["ticket_id", "customer_id", "summary", "priority", "status", "request_id"],
    }


@app.post("/v1/runs", response_model=RunAccepted, status_code=202)
async def submit_run(payload: RunCreate) -> RunAccepted:
    try:
        settings = load_model_settings()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Model configuration is missing. Check the project .env file.") from exc
    contains_configured_key = bool(settings.api_key and settings.api_key in payload.message)
    if contains_configured_key or SECRET_PATTERN.search(payload.message):
        raise HTTPException(
            status_code=400,
            detail="Do not enter API keys, passwords, or other credentials in the chat.",
        )
    request = AgentRequest(
        message=payload.message,
        customer_id="CUST-100",
        authenticated=True,
        allow_ticket_creation=True,
    )
    managed = RUNS.submit(request, settings)
    return RunAccepted(run_id=managed.run_id, status="queued", events_url=f"/v1/runs/{managed.run_id}/events")


@app.get("/v1/runs")
async def history(limit: int = Query(default=50, ge=1, le=100)) -> list[dict[str, object]]:
    return RUNS.history(limit)


@app.get("/v1/runs/{run_id}")
async def run_detail(run_id: str) -> dict[str, object]:
    record = RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    record["events"] = RUNS.events(run_id)
    return record


@app.get("/v1/runs/{run_id}/compare/{other_run_id}")
async def compare_runs(run_id: str, other_run_id: str) -> dict[str, object]:
    before = RUNS.get(run_id)
    after = RUNS.get(other_run_id)
    if before is None or after is None:
        raise HTTPException(status_code=404, detail="Both saved runs must exist before comparison.")

    def comparison_record(record: dict[str, object]) -> dict[str, object]:
        result = record.get("result")
        if not isinstance(result, dict):
            return {"run_id": record["run_id"], "status": record["status"], "result": None}
        request = record.get("request", {})
        return {
            "run_id": record["run_id"],
            "status": record["status"],
            "customer_id": request.get("customer_id") if isinstance(request, dict) else None,
            "message": request.get("message") if isinstance(request, dict) else None,
            "implementation_fingerprint": result.get("implementation_fingerprint"),
            "model_name": result.get("model_name"),
            "prompt_version": result.get("prompt_version"),
            "dataset_version": result.get("dataset_version"),
            "resource_limits": result.get("resource_limits"),
            "output": result.get("output"),
            "tool_calls": result.get("tool_calls"),
            "final_state": result.get("final_state"),
            "metrics": {
                "model_turns": result.get("model_turns"),
                "input_tokens": result.get("input_tokens"),
                "output_tokens": result.get("output_tokens"),
                "latency_ms": result.get("latency_ms"),
                "estimated_cost_usd": result.get("estimated_cost_usd"),
            },
        }

    return {"before": comparison_record(before), "after": comparison_record(after)}


@app.get("/v1/runs/{run_id}/events")
async def run_events(run_id: str, after: int = Query(default=0, ge=0)) -> StreamingResponse:
    if RUNS.get(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_stream() -> AsyncIterator[str]:
        last_id = after
        while True:
            events = RUNS.events(run_id, last_id)
            for event in events:
                last_id = event["id"]
                payload = json.dumps(event["data"], ensure_ascii=True)
                yield f"id: {last_id}\nevent: {event['event']}\ndata: {payload}\n\n"
            record = RUNS.get(run_id)
            if record is None or record["status"] in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(0.1)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/v1/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, object]:
    result = RUNS.cancel(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    accepted, state = result
    return {"run_id": run_id, "accepted": accepted, "status": state}


@app.post("/v1/runs/{run_id}/replay", response_model=RunAccepted, status_code=202)
async def replay_run(run_id: str) -> RunAccepted:
    try:
        settings = load_model_settings()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Model configuration is missing. Check the project .env file.") from exc
    managed = RUNS.replay(run_id, settings)
    if managed is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunAccepted(run_id=managed.run_id, status="queued", events_url=f"/v1/runs/{managed.run_id}/events")


@app.get("/v1/runs/{run_id}/data")
async def run_data(run_id: str) -> dict[str, object]:
    result = RUNS.data_snapshot(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Run data is not available")
    return result


@app.get("/v1/runs/{run_id}/export")
async def export_run(run_id: str) -> dict[str, object]:
    record = RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "record_type": "synthetic_classroom_evidence",
        "run": record,
        "events": RUNS.events(run_id),
        "data_snapshot": RUNS.data_snapshot(run_id),
        "rca_template": rca_record_template(),
    }
