from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from src.config import ATTEMPTS_DIR, HISTORY_DB, SEED_DB


CUSTOMERS = (
    (
        "CUST-100", "Maya Example", "maya.cust100@example.test", "TEST-PHONE-100",
        "SIMULATED ADDRESS 100 — NOT A REAL ADDRESS", "Staff note: requested extra follow-up.",
        "manual_review_demo",
    ),
    (
        "CUST-200", "Rafi Example", "rafi.cust200@example.test", "TEST-PHONE-200",
        "SIMULATED ADDRESS 200 — NOT A REAL ADDRESS", "Staff note: prefers email contact.",
        "standard_demo",
    ),
    (
        "CUST-300", "Nia Example", "nia.cust300@example.test", "TEST-PHONE-300",
        "SIMULATED ADDRESS 300 — NOT A REAL ADDRESS", "Staff note: test-only guest profile.",
        "guest_demo",
    ),
)


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def create_app_schema(path: Path) -> None:
    with connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS customers (
                customer_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL,
                shipping_address TEXT NOT NULL,
                internal_notes TEXT NOT NULL,
                review_flag TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL,
                request_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
            );
            """
        )


def seed_database(path: Path, *, overwrite: bool = False) -> None:
    if overwrite and path.exists():
        path.unlink()
    create_app_schema(path)
    with connect(path) as connection:
        current = connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        if current == 0:
            connection.executemany(
                """INSERT INTO customers(
                    customer_id, display_name, email, phone, shipping_address,
                    internal_notes, review_flag
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                CUSTOMERS,
            )


def create_history_schema(path: Path = HISTORY_DB) -> None:
    with connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                submitted_at TEXT NOT NULL,
                status TEXT NOT NULL,
                request_json TEXT NOT NULL,
                result_json TEXT,
                error_category TEXT
            );
            CREATE TABLE IF NOT EXISTS run_events (
                run_id TEXT NOT NULL,
                event_id INTEGER NOT NULL,
                event TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                data_json TEXT NOT NULL,
                PRIMARY KEY(run_id, event_id),
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );
            """
        )


def new_attempt_database(run_id: str) -> Path:
    ATTEMPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = ATTEMPTS_DIR / f"{run_id}.sqlite"
    shutil.copy2(SEED_DB, path)
    return path


def database_snapshot(path: Path) -> dict[str, Any]:
    with connect(path) as connection:
        customers = [dict(row) for row in connection.execute(
            "SELECT * FROM customers ORDER BY customer_id"
        )]
        tickets = [dict(row) for row in connection.execute(
            "SELECT * FROM tickets ORDER BY ticket_id"
        )]
    return {"customers": customers, "tickets": tickets}


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)
