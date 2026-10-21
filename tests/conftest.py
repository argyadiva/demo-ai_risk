from pathlib import Path

import pytest

from src.config import ModelSettings
from src.db import seed_database


@pytest.fixture
def app_db(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.sqlite"
    seed_database(path)
    return path


@pytest.fixture
def settings() -> ModelSettings:
    return ModelSettings(api_key="offline-test-credential", agent_model="offline-test")
