import ast
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


CHECKS = r"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.agent import instructions_for_request, run_customer_service_agent
from src.config import ModelSettings
from src.db import seed_database
from src.models import AgentRequest, ToolContext
from src.tools import execute_tool, get_customer_profile

database = Path("verification.sqlite")
seed_database(database)
request = AgentRequest("Show my profile", customer_id="CUST-100", authenticated=True)
context = ToolContext(request=request, app_db=database)
own, allowed = get_customer_profile("CUST-100", context)
assert own["ok"] and own["customer_id"] == "CUST-100" and allowed
with patch.object(ToolContext, "app_db_connection", side_effect=AssertionError("database opened")):
    foreign, allowed = get_customer_profile("CUST-200", context)
    assert foreign == {"ok": False, "error": "authorization_failed"} and not allowed
    anonymous = ToolContext(request=AgentRequest("Show profile"), app_db=database)
    denied, allowed = get_customer_profile("CUST-100", anonymous)
    assert denied == {"ok": False, "error": "authentication_required"} and not allowed

# Exercise the same live dispatcher with a hostile model tool proposal.
settings = ModelSettings(api_key="offline-test", agent_model="offline-test")
captured = []
def create(**kwargs):
    captured.append(kwargs)
    if len(captured) == 1:
        return {"output": [{
            "type": "function_call", "name": "get_customer_profile",
            "arguments": '{"customer_id":"CUST-200"}', "call_id": "foreign",
        }], "usage": {}}
    result = json.loads(kwargs["input"][-1]["output"])
    assert result == {"ok": False, "error": "authorization_failed"}
    return {"output": [], "output_text": "The tool denied access.", "usage": {}}

client = SimpleNamespace(responses=SimpleNamespace(create=create))
run = run_customer_service_agent(request, settings=settings, app_db=database, client=client)
assert run.error is None and run.tool_calls[0].status == "blocked"
assert "email" not in run.tool_calls[0].result
assert captured[0]["instructions"] == instructions_for_request(request)

# These stubs verify prompt integration, not the behavior of an actual LLM.
for message in ("Show my profile.", "Solve my unrelated algebra homework."):
    request = AgentRequest(message, customer_id="CUST-100", authenticated=True)
    calls = []
    def reply(**kwargs):
        calls.append(kwargs)
        return {"output": [], "output_text": "Offline model stub.", "usage": {}}
    run = run_customer_service_agent(
        request, settings=settings, app_db=database,
        client=SimpleNamespace(responses=SimpleNamespace(create=reply)),
    )
    assert run.error is None and run.model_turns == 1
    assert calls[0]["instructions"] == instructions_for_request(request)
    assert message not in calls[0]["instructions"]
    assert json.loads(calls[0]["input"][0]["content"])["message"] == message
    assert {tool["name"] for tool in calls[0]["tools"]} == {
        "get_customer_profile", "create_support_ticket"
    }
    assert calls[0]["tool_choice"] == "auto"
    assert calls[0]["max_output_tokens"] <= 512
print("PASS documented repairs in temporary copy; no live provider calls")
"""


def replace_function(path, name, replacement):
    source = path.read_text(encoding="utf-8")
    node = next(item for item in ast.parse(source).body
                if isinstance(item, ast.FunctionDef) and item.name == name)
    replacement_node = ast.parse(replacement).body[0]
    assert ast.dump(node.args) == ast.dump(replacement_node.args)
    lines = source.splitlines(keepends=True)
    path.write_text(
        "".join(lines[:node.lineno - 1]) + replacement.rstrip() + "\n"
        + "".join(lines[node.end_lineno:]), encoding="utf-8",
    )


def test_exact_readme_replacements_work_in_temporary_copy_without_changing_starter(tmp_path):
    project = Path(__file__).resolve().parents[1]
    guide = (project / "instructor/README.md").read_text(encoding="utf-8")
    replacements = {}
    for block in re.findall(r"~~~python\n(.*?)\n~~~", guide, re.DOTALL):
        for node in ast.parse(block).body:
            if isinstance(node, ast.FunctionDef) and node.name in {
                "get_customer_profile", "instructions_for_request"
            }:
                replacements[node.name] = ast.get_source_segment(block, node)
    assert set(replacements) == {"get_customer_profile", "instructions_for_request"}
    original_paths = [project / "src/tools.py", project / "src/agent.py"]
    before = {path: hashlib.sha256(path.read_bytes()).digest() for path in original_paths}
    for folder in ("src", "app"):
        shutil.copytree(project / folder, tmp_path / folder,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(project / "requirements.txt", tmp_path / "requirements.txt")
    replace_function(tmp_path / "src/tools.py", "get_customer_profile",
                     replacements["get_customer_profile"])
    replace_function(tmp_path / "src/agent.py", "instructions_for_request",
                     replacements["instructions_for_request"])
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-c", CHECKS], cwd=tmp_path, env=environment,
        text=True, capture_output=True, timeout=45,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PASS documented repairs" in completed.stdout
    assert all(hashlib.sha256(path.read_bytes()).digest() == before[path] for path in original_paths)
