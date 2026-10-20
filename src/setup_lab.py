from __future__ import annotations

import argparse

from src.config import HISTORY_DB, SEED_DB
from src.db import create_history_schema, seed_database


def setup(*, reset_seed: bool = False) -> None:
    seed_database(SEED_DB, overwrite=reset_seed)
    create_history_schema(HISTORY_DB)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the Module 15 local challenge")
    parser.add_argument(
        "--reset-seed",
        action="store_true",
        help="Rebuild only the synthetic starter database; saved attempts are retained.",
    )
    args = parser.parse_args()
    setup(reset_seed=args.reset_seed)
    print(f"Synthetic seed database ready: {SEED_DB}")
    print(f"Attempt history is retained in: {HISTORY_DB}")
    print("Three synthetic customer records are ready. No API calls were made.")


if __name__ == "__main__":
    main()
