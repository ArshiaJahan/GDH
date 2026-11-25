"""Fingerprint published prompt improver evals so prompt or config drift is visible."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = 1


def compute(config: Any = None, corpus_path: Path | None = None) -> dict:
    """Hash the evaluator inputs that determine a live regression result."""
    from . import pi_research, prompt_improver
    from .pi_contracts import TEMPLATE_VERSION

    if config is None:
        from ..config import get_config
        config = get_config()
    raw = getattr(config, "prompt_improver", None)
    settings = {**prompt_improver.DEFAULTS, **(raw if isinstance(raw, dict) else {})}
    model = config.resolve(str(settings["model"]))
    h = hashlib.sha256()
    for part in (prompt_improver.EVAL_SYSTEM, prompt_improver.SYNTH_SPEC,
                 prompt_improver.FORMAT_SPEC, prompt_improver.DECISION_RULES):
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    h.update(json.dumps(pi_research.QUESTION_BANK, sort_keys=True).encode("utf-8"))
    path = corpus_path or Path(__file__).resolve().parents[3] / "tests/fixtures/prompt_improver/prompts.json"
    return {
        "template_version": TEMPLATE_VERSION,
        "prompt_sha256": h.hexdigest(),
        "models": {"prompt_improver": model},
        "settings": {key: settings[key] for key in ("effort", "max_calls", "max_questions", "max_input_tokens", "max_output_tokens")},
        "corpus_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def digest(fp: dict) -> str:
    """Return a stable digest for a fingerprint object."""
    raw = json.dumps(fp, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def diff(old: dict, new: dict) -> list[str]:
    """List changed fingerprint leaves in stable dotted-name order."""
    out: list[str] = []
    def walk(a: Any, b: Any, prefix: str) -> None:
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                name = f"{prefix}.{key}" if prefix else key
                if key not in a or key not in b:
                    out.append(name)
                else:
                    walk(a[key], b[key], name)
        elif a != b:
            out.append(prefix)
    walk(old, new, "")
    return out


def render_md(doc: dict) -> str:
    """Render only recorded publication fields, preserving summary key order."""
    rows = ["# Prompt improver eval", "", f"- Ran at: {doc['ran_at']}", f"- Git SHA: {doc['git_sha']}",
            f"- Model: {doc['model']}", f"- Calls: {doc['calls']}", f"- Cost (USD): {doc['cost_usd']}", "",
            "## Fingerprint", "", "| Component | Value |", "|---|---|"]
    fp = doc["fingerprint"]
    rows.extend(f"| {key} | {json.dumps(value, sort_keys=True, separators=(',', ':'))} |" for key, value in fp.items())
    rows += ["", "## Summary", "", "| Metric | Value |", "|---|---|"]
    for key, value in doc["summary"].items():
        if isinstance(value, dict):
            value = " / ".join(_fmt(v) for v in value.values())
        else:
            value = _fmt(value)
        rows.append(f"| {key} | {value} |")
    return "\n".join(rows) + "\n"


def _fmt(value: Any) -> str:
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def check(published_json: Path, published_md: Path, current: dict) -> dict:
    """Validate the published pair, then compare its recorded inputs with current inputs."""
    if not published_json.exists():
        return {"status": "never_run", "changed": [], "message": "prompt improver eval has never run"}
    try:
        doc = json.loads(published_json.read_text(encoding="utf-8"))
        required = {"schema", "fingerprint", "digest", "mode", "ran_at", "summary"}
        if (not isinstance(doc, dict) or not required.issubset(doc) or doc["schema"] != SCHEMA or
                doc["mode"] != "live" or doc["digest"] != digest(doc["fingerprint"]) or
                not published_md.is_file() or published_md.read_text(encoding="utf-8") != render_md(doc)):
            raise ValueError("invalid published eval")
    except (OSError, ValueError, TypeError, KeyError):
        return {"status": "invalid", "changed": [], "message": "published prompt improver eval is invalid"}
    changed = diff(doc["fingerprint"], current)
    if changed:
        names = ", ".join(changed)
        return {"status": "stale", "changed": changed,
                "message": f"prompt improver eval is stale (changed: {names}). Re-run it with: uv run python scripts/eval_regression.py run --approve-paid"}
    return {"status": "current", "changed": [], "message": "prompt improver eval is current"}
