"""Eval Forge v0, part 4: export to the Harbor task format (Terminal-Bench 2.0), and run the exported scripts."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from gamedevworkstation.features import eval_cli, eval_export, eval_forge, eval_task

from .evalrepo import make_repo

pytestmark = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="exported scripts are bash")


@pytest.fixture
async def task(tmp_path):
    repo = make_repo(tmp_path)
    return eval_task.load(await eval_forge.forge(repo, "HEAD", tmp_path / "suite", task_id="scores-task"))


def test_layout_and_task_toml(task, tmp_path):
    d = eval_export.export(task, tmp_path / "harbor")
    for rel in ("instruction.md", "task.toml", "environment/Dockerfile", "solution/solve.sh", "solution/solution.patch",
                "tests/test.sh", "tests/files/tests/test_scores.py", "environment/repo/src/scores.py"):
        assert (d / rel).is_file(), rel
    cfg = tomllib.loads((d / "task.toml").read_text(encoding="utf-8"))
    assert cfg["schema_version"] == "1.4" and cfg["task"]["name"] == "gdh/scores-task"
    assert cfg["verifier"]["timeout_sec"] == 900.0 and cfg["agent"]["timeout_sec"] == 1800.0
    assert cfg["environment"]["workdir"] == "/app" and cfg["metadata"]["start_commit"] == task.task.source.parent
    # the start state, without the solution or the hidden tests
    assert "clamp_score" not in (d / "environment/repo/src/scores.py").read_text(encoding="utf-8")
    assert not (d / "environment/repo/tests").exists()
    assert "clamp_score" not in (d / "instruction.md").read_text(encoding="utf-8")
    df = (d / "environment/Dockerfile").read_text(encoding="utf-8")
    assert "COPY repo/ /app/" in df and "WORKDIR /app" in df and "pytest" in df
    assert os.access(d / "tests/test.sh", os.X_OK) and os.access(d / "solution/solve.sh", os.X_OK)


def _run(script: Path, app: Path, d: Path, reward: Path) -> str:
    env = {**os.environ, "APP": str(app), "TESTS": str(d / "tests"), "SOLUTION": str(d / "solution"),
           "REWARD": str(reward), "PATH": os.pathsep.join([str(Path(sys.executable).parent), os.environ["PATH"]])}
    r = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return reward.read_text(encoding="utf-8").strip()


def test_the_exported_verifier_and_oracle_work(task, tmp_path):
    d = eval_export.export(task, tmp_path / "harbor")
    for name, solve, want in (("oracle", True, "1"), ("untouched", False, "0")):
        app = tmp_path / name
        shutil.copytree(d / "environment" / "repo", app)
        if solve:
            subprocess.run(["bash", str(d / "solution/solve.sh")], check=True,
                           env={**os.environ, "APP": str(app), "SOLUTION": str(d / "solution")})
        assert _run(d / "tests/test.sh", app, d, tmp_path / f"{name}.reward") == want, name
    # An agent that rewrote the tests still gets the originals.
    app = tmp_path / "tamper"
    shutil.copytree(d / "environment" / "repo", app)
    (app / "tests").mkdir()
    (app / "tests" / "test_scores.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    assert _run(d / "tests/test.sh", app, d, tmp_path / "tamper.reward") == "0"


def test_gdw_only_graders_are_listed_not_exported(task, tmp_path):
    t = task.task.model_copy(deep=True)
    t.grader.rubric = True
    d = eval_export.export(task.model_copy(update={"task": t}), tmp_path / "harbor")
    cfg = tomllib.loads((d / "task.toml").read_text(encoding="utf-8"))
    assert cfg["metadata"]["graders_not_exported"] == ["rubric"]
    t.grader.command = ""
    with pytest.raises(eval_export.ExportError, match="nothing to export"):
        eval_export.export(task.model_copy(update={"task": t}), tmp_path / "harbor2")


def test_clone_url_and_cli(task, tmp_path, capsys):
    d = eval_export.export(task, tmp_path / "harbor", clone_url="https://github.com/o/r.git")
    df = (d / "environment/Dockerfile").read_text(encoding="utf-8")
    assert f"git -C /app checkout --detach {task.task.source.parent}" in df and not (d / "environment/repo").exists()
    assert eval_cli.cli(["export", str(task.dir), "--out", str(tmp_path / "h2")]) == 0
    assert "scores-task:" in capsys.readouterr().out
    assert eval_cli.cli(["export", str(task.dir), "--out", str(tmp_path / "h2")]) == 1  # already there


def test_docker_setup_is_image_only(task, tmp_path):
    d = eval_export.export(task, tmp_path / "harbor", docker_setup="pip install -e . pytest-asyncio")
    df = (d / "environment/Dockerfile").read_text(encoding="utf-8")
    assert df.rstrip().endswith("RUN pip install -e . pytest-asyncio") and df.index("WORKDIR /app") < df.index("RUN pip install -e")
    assert eval_task.load(task.dir).task.grader.setup == ""  # the task itself is unchanged
