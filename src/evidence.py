from __future__ import annotations

from typing import Any


MISSION_IDS = {
    "profile_boundary", "resource_budget", "data_minimization",
    "truthful_actions", "ticket_idempotency",
}




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
