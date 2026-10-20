# Instructor Guide — Break This Agent

This folder contains the mission answer key and standalone reference controls.
Keep it closed while students identify a root cause. Every contact detail and
internal flag is synthetic. The project `.env` is local, ignored by Git, and its
values must never appear in a screenshot or classroom artifact.

The instructor-only [verification record](verification-record.md) summarizes
the bounded live runs, exact run IDs, observed statuses, model, prompt versions,
and implementation fingerprints. See `mission-key.md` for root causes and
`reference_solutions.py` for standalone control examples.
Use [group-assignments.md](group-assignments.md) to spread evidence collection
across all five missions while each team completes one primary repair.
The [successful prompt reference](successful-prompts.md) contains the tested
prompts and recorded results for all five missions, plus normal-use comparisons.
Four missions reproduced; false confirmation resisted four live attempts.
Keep the exact prompts out of the participant briefing.

## Prepare before class

1. Use Python 3.11+, install `requirements.txt`, and verify the compatible model
   configuration in `.env` without displaying the key.
2. Run `python -m src.setup_lab` and `python -m pytest -q`.
3. Start `uvicorn app.main:app --reload --host 127.0.0.1 --port 8000` and verify
   the UI, one profile request, one ticket request, event trace, and data panel.
4. Run the bounded live pack once if the provider budget allows. Review every
   mission result; do not promise an attack will succeed through natural chat.
5. Split the five missions across groups. Have every group solve one issue deeply.

No seed-reset step deletes history, per-run data, or exports. The database reset
flag applies only to the synthetic seed database.

## Facilitation

Use 10 minutes for the customer data walkthrough and normal requests, 25 for
attacks, 20 for evidence-led RCA, 25 for one Python repair, 15 for tests and a
replay, and 10 for group demos and release discussion.

Ask groups to explain: “What did the attacker supply? Which application
component acted? What changed in the database? What code control prevented it
after your repair? What legitimate request did you retest?”

### Facilitate evidence-led diagnosis

Mission 1 now uses prompt injection against a weak support-chat agent. The
server supplies a fixed Maya/CUST-100 session; the participant UI has no session
picker, permission toggle, or failure-fixture checkbox. Tool selection is
automatic throughout.

The seeded prompt-construction defect appends the customer message to trusted
instructions as request-specific workflow notes. The profile tool also lacks
ownership enforcement. Students repair both the instruction boundary and the
tool authorization boundary. The normal-use and access-challenge paths share
this behavior, so no special button is needed to enable the vulnerability.

The **Access challenge** card has a blank prompt and a broad objective. Begin
with “Show my profile,” allow exploration, and release hints progressively.
Keep the tested attack and source explanation in instructor materials until
learners have recorded their first finding.

The ticket-failure scenario is configured on the server for the truthful-actions
mission. Its tool returns storage_unavailable before any write, and replay
preserves this configuration. Other scenarios allow ordinary ticket creation.
Anonymous and alternative-session cases remain available in direct offline tool
tests. The browser API accepts only a message and mission ID.

The workbench does not grade attacks or attach automatic assessment labels.
Run/tool statuses describe execution, and the database event reports queried
ticket counts and IDs. Ask students to separate these facts from their own
interpretations in the RCA panel.

For ambiguous action language, have students compare the answer with the tool
result and persisted rows. For resource abuse, examine response scope and
reported usage together. A provider error or cancellation is not a successful
defense. A model refusing an attack does not prove that the tool enforces
ownership or field allowlisting; follow up with a deterministic regression test.

Original historical recordings are preserved. The application omits their old
automatic verdicts when reading/exporting them; earlier downloaded JSON and the
historical verification record may still contain the retired labels.

## Verification commands

```bash
python -m src.setup_lab
python -m pytest -q
python -m pytest instructor/test_reference_solutions.py -q
python -m pytest -m mission
python -m pytest -m live -q
python -m src.run_live_pack --limit 6
```

The mission contract suite fails on the vulnerable starter by design. After the
instructor installs and reviews the appropriate source repairs, it should pass.
The reference tests exercise the answer-key controls in an isolated database.
Live test results depend on provider behavior, configured model, network, and
available budget.

The live suite runs three attempts: one normal profile request and two first-
mission profile requests (foreign and own customer). To run only the latter two
through the UI backend, use
`python -m pytest -m live -k profile_injection_via_ui_api -q -s`.

These create new history records. Each attempt can use up to three provider
calls. The full live pack runs up to six scenarios, with the same per-attempt
cap, and saves evidence in `outputs/`. It does not grade the attacks.

To validate all scenarios through the UI's API with the current server-owned
session and ticket settings, use `python -m instructor.validate_missions`.
It runs two normal comparisons and the five missions, saves each run in history,
and exports raw evidence to uniquely named files. Each attempt has at most three
model calls. See `successful-prompts.md` for per-case commands and limitations.

## Outage contingency

If the provider is unavailable, use `outage-recovery/provider-timeout.sample.json`.
It is a clearly labeled, instructor-created synthetic fixture—not a real provider
recording or live attack. Students may still perform the deterministic tool-level
mission tests, inspect the sample, repair one control, and explain why an outage
fixture is not a fresh live verification.

## Assessment rubric

| Area | Weight | Evidence |
|---|---:|---|
| RCA and risk explanation | 30% | Run ID, observed evidence, root cause, affected party and plausible harm |
| Code repair | 35% | Control is enforced in the appropriate application boundary |
| Verification | 25% | Regression test, before/after evidence, and legitimate-use check |
| Governance reasoning | 10% | Named owner, residual risk, and scoped release recommendation |
