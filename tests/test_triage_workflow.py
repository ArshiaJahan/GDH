"""Static checks on the CI triage workflow and composite action (they run with a write token)."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
ACTION = ROOT / ".github" / "actions" / "triage" / "action.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _on(doc: dict) -> dict:
    # PyYAML parses the bare key `on` as the boolean True.
    return doc.get("on", doc.get(True))


@pytest.fixture(scope="module")
def triage():
    return _load(WF / "triage.yml")


@pytest.fixture(scope="module")
def action():
    return _load(ACTION)


def test_trigger_is_workflow_run_on_ci_completed(triage):
    ci_name = _load(WF / "ci.yml")["name"]
    assert ci_name == "CI"
    assert _on(triage) == {"workflow_run": {"workflows": [ci_name], "types": ["completed"]}}


def test_failure_only_and_permissions(triage):
    assert triage["name"] == "CI triage"
    assert triage["permissions"] == {"actions": "read", "contents": "read", "pull-requests": "write"}
    (job,) = triage["jobs"].values()
    assert job["if"] == "github.event.workflow_run.conclusion == 'failure'"
    assert "workflow_run.id" in triage["concurrency"]["group"]


def test_never_checks_out_pr_code(triage):
    text = (WF / "triage.yml").read_text(encoding="utf-8")
    for bad in ("head_sha", "head_branch", "head_repository"):
        assert bad not in text
    (job,) = triage["jobs"].values()
    checkouts = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout")]
    assert checkouts
    for s in checkouts:
        assert "ref" not in (s.get("with") or {})
        assert s["with"]["persist-credentials"] is False
    uses = [s for s in job["steps"] if s.get("uses") == "./.github/actions/triage"]
    assert len(uses) == 1
    w = uses[0]["with"]
    assert w["run-id"] == "${{ github.event.workflow_run.id }}"
    assert w["comment-pr"] == "${{ github.event.workflow_run.pull_requests[0].number }}"


def test_action_passes_inputs_through_env(action):
    assert action["name"] == "GDH CI triage"
    assert action["runs"]["using"] == "composite"
    assert action["inputs"]["run-id"]["required"] is True
    runs = [s for s in action["runs"]["steps"] if "run" in s]
    assert runs
    for s in runs:
        assert "${{ inputs." not in s["run"]
        assert s["shell"] == "bash"
    script = runs[-1]
    assert {"RUN_ID", "REPO", "PR", "GH_TOKEN"} <= set(script["env"])
    assert "gdw" in script["run"] and "triage" in script["run"] and "--summary" in script["run"]
    assert '--comment "$PR"' in script["run"]
    assert "--frozen" in script["run"] and "--project" in script["run"] and "--no-dev" in script["run"]
    assert "uvx" not in script["run"]
    for s in runs:
        assert "${{ github.action_path }}" not in s["run"]
    assert any(str(s.get("uses", "")).startswith("astral-sh/setup-uv@v6") for s in action["runs"]["steps"])


@pytest.mark.skipif(shutil.which("actionlint") is None, reason="actionlint not installed")
def test_actionlint():
    r = subprocess.run(["actionlint", str(WF / "triage.yml")], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
