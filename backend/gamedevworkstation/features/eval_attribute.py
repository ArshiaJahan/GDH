"""Eval Forge failure attribution: who does a failed trial blame, the agent, the environment or the grader?

Rules, first match wins (each gives a reason that names its evidence):

environment
- the agent never ran properly: CLI missing, login/auth failure, rate limit, crash before any work
- a grading step failed in a way that is the machine's fault (command not found, timeout, failed setup, no
  Unity), or the CI-triage classifier puts the failing output in infra / dependency / timeout
grader
- the task has no validation report, or its reference solution failed validation: a failure says nothing
- deterministic graders passed and only the model rubric failed: the judge disagrees with the tests
agent
- everything else: the grader is validated and the environment was fine, so the work was wrong
  (tampering with the hidden tests is noted in the reason)

A pass is never attributed. Low kill rates don't move blame to the grader by themselves (a failing agent
still failed the reference-validated tests); they're reported next to the score instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import triage_rules
from .eval_grade import Grade

ENV_CATEGORIES = {"infra", "dependency", "timeout"}
_AGENT_ENV = re.compile(r"not installed|command not found|No such file or directory: '(claude|codex)'|not logged in|"
                        r"login|authenticat|unauthori[sz]ed|401|403|rate.?limit|429|overloaded|quota|ENOTFOUND|"
                        r"ECONNRESET|network", re.I)


@dataclass
class Attribution:
    blame: str      # "" (passed) | agent | environment | grader
    reason: str


def attribute(grade: Grade | None, *, agent_error: str = "", agent_timed_out: bool = False,
              validation: dict | None = None) -> Attribution:
    if grade is not None and grade.passed and not agent_error:
        return Attribution("", "passed")
    if agent_error and _AGENT_ENV.search(agent_error):
        return Attribution("environment", f"the agent couldn't run: {agent_error[:200]}")
    if grade is None:
        # The agent stopped before there was anything to grade; a timeout is the agent's (it had the budget).
        if agent_timed_out:
            return Attribution("agent", "the agent ran out of its time limit")
        return Attribution("environment", f"the agent failed to start or crashed: {agent_error[:200] or 'no output'}")
    failed = [s for s in grade.steps if not s.passed]
    env_steps = [s for s in failed if s.environment]
    if env_steps:
        s = env_steps[0]
        return Attribution("environment", f"{s.kind} step {s.name!r} failed for the environment: "
                                          f"{_first_line(s.output) or 'exit ' + str(s.exit)}")
    for s in failed:
        if s.kind in ("command", "check") and s.output:
            cats = {f.category for f in triage_rules.classify(s.output, s.name).failures}
            if cats & ENV_CATEGORIES:
                return Attribution("environment", f"{s.name!r} output looks like {', '.join(sorted(cats & ENV_CATEGORIES))} "
                                                  "(CI triage rules)")
    if not validation:
        return Attribution("grader", "the task's grader was never validated (run gdw eval validate)")
    if not validation.get("reference_passed"):
        return Attribution("grader", "the reference solution failed this grader in validation")
    if failed and all(s.kind == "rubric" for s in failed):
        return Attribution("grader", "only the model rubric failed; the deterministic graders passed")
    tamper = f" (it also changed hidden tests: {', '.join(grade.tampered)})" if grade.tampered else ""
    names = ", ".join(f"{s.kind} {s.name!r}" for s in failed) or "the grader"
    return Attribution("agent", f"failed {names}{tamper}")


def _first_line(text: str) -> str:
    for line in reversed((text or "").strip().splitlines()):
        if line.strip():
            return line.strip()[:200]
    return ""
