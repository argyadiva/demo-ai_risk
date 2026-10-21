from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
ATTEMPTS_DIR = DATA_DIR / "attempts"
SEED_DB = DATA_DIR / "seed.sqlite"
HISTORY_DB = DATA_DIR / "history.sqlite"
PROMPT_VERSION = "module16-single-agent-v1"
DATASET_VERSION = "northstar-synthetic-2026-10-20"


@dataclass(frozen=True)
class ModelSettings:
    api_key: str
    agent_model: str
    base_url: str | None = None
    input_cost_per_1m: float | None = None
    output_cost_per_1m: float | None = None
    hard_max_model_turns: int = 3
    hard_max_tool_calls: int = 3
    hard_max_output_tokens_per_turn: int = 512


def load_model_settings() -> ModelSettings:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    api_key = os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
    agent_model = os.getenv("AGENT_MODEL")
    missing = [name for name, value in (("API_KEY", api_key), ("AGENT_MODEL", agent_model)) if not value]
    if missing:
        raise RuntimeError("Missing model configuration: " + ", ".join(missing))

    def optional_rate(name: str) -> float | None:
        raw = os.getenv(name)
        if not raw:
            return None
        try:
            value = float(raw)
        except ValueError as exc:
            raise RuntimeError(f"{name} must be a non-negative number") from exc
        if value < 0:
            raise RuntimeError(f"{name} must be a non-negative number")
        return value

    def bounded_integer(name: str, default: int, maximum: int) -> int:
        raw = os.getenv(name, str(default))
        try:
            value = int(raw)
        except ValueError as exc:
            raise RuntimeError(f"{name} must be an integer") from exc
        if not 1 <= value <= maximum:
            raise RuntimeError(f"{name} must be between 1 and {maximum}")
        return value

    return ModelSettings(
        api_key=api_key or "",
        agent_model=agent_model or "",
        base_url=os.getenv("API_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
        input_cost_per_1m=optional_rate("INPUT_COST_PER_1M"),
        output_cost_per_1m=optional_rate("OUTPUT_COST_PER_1M"),
        hard_max_model_turns=bounded_integer("HARD_MAX_MODEL_TURNS", 3, 3),
        hard_max_tool_calls=bounded_integer("HARD_MAX_TOOL_CALLS", 3, 3),
        hard_max_output_tokens_per_turn=bounded_integer(
            "HARD_MAX_OUTPUT_TOKENS_PER_TURN", 512, 512
        ),
    )
