from __future__ import annotations

from pathlib import Path

import pytest

from src.db import seed_database


@pytest.fixture
def app_db(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.sqlite"
    seed_database(path)
    return path
