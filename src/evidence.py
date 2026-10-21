from __future__ import annotations

from typing import Any


def rca_record_template() -> dict[str, Any]:
    return {
        "finding": "",
        "run_id": "",
        "reproducing_request": "",
        "observed_evidence": "",
        "responsible_component": "",
        "root_cause": "",
        "affected_party_and_harm": "",
        "control_change": "",
        "regression_test": "",
        "before_after_result": "",
        "control_owner": "",
        "remaining_risk": "",
        "release_recommendation": "",
    }
