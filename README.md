# Module 16: One Agent, Two Fixes

Continue the Module 15 customer-support agent in a short guided walkthrough. You chat with one agent signed in as Maya/CUST-100. It has profile lookup and ticket creation tools, execution traces, saved history, replay, comparison, and evidence export.

The source intentionally starts with a missing profile-ownership check and a permissive general-purpose prompt. Your instructor and you will paste two complete replacement functions from [the walkthrough](instructor/README.md) into the existing source.

## Run the agent

Use Python 3.11 or newer. From project_v2:

~~~powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m src.setup_lab
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
~~~

For macOS/Linux, activate with source .venv/bin/activate. Copy .env.example to a private .env and configure your provider before using live chat. Open http://127.0.0.1:8000.

Start with “Show my customer profile.” Use ordinary language; the browser submits only your message, and the server owns identity and permissions.

## Apply the two changes

| Problem | Change | Where to paste it |
|---|---|---|
| Access challenge | Validate requested customer ID against the authenticated session before reading a row. | get_customer_profile in src/tools.py |
| Free homework machine | Replace the permissive instructions with a support-only system prompt. | instructions_for_request in src/agent.py |

Both complete functions, demonstration requests, and expected before/after checks are in instructor/README.md. The ownership check is enforced by code. The prompt is a behavioral mitigation and still uses a model call; it does not guarantee rejection of all unrelated work.

## Check the project

~~~powershell
python -m pytest -q
~~~

All ordinary tests should pass in the shipped starter. The suite also validates the README replacements in a temporary copy and verifies that your local source was not changed by that check. No provider calls are made by the test suite.

The [instructor verification record](instructor/verification-record.md) documents 18 passing offline tests and six separate live probes of the exact replacements. Live observations are bounded evidence, not a guarantee of prompt compliance.

Every chat submission and replay creates a fresh synthetic attempt database. Replay retains previous evidence and executes the request against the currently loaded code. After editing a function, let Uvicorn reload before replaying. Saved history from the previous project remains readable; obsolete scenario fields are ignored during replay.

Use only the provided synthetic customer records. Keep API keys out of messages, exports, screenshots, and submissions. The remaining agent behavior is retained for continuity with Module 15; these two edits are not a claim that every production concern has been addressed.
