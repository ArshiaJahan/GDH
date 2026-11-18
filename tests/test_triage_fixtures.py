"""Label integrity and accuracy of the CI triage rules over tests/fixtures/ci_logs.

Every labels*.json is a list of {file, category, path, line, test, origin, note} giving the ground
truth PRIMARY failure of one fixture log. The integrity tests always run; test_fixture_accuracy
measures features/triage_rules.py against the labels (skipped until that module exists)."""
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "ci_logs"
CATEGORIES = {"compile", "test", "flaky", "infra", "dependency", "timeout", "unknown"}
ORIGINS = {"real-gdh-ci", "generated", "handwritten"}

# Thresholds: the director adjusts these after measuring.
MIN_CATEGORY_ACCURACY = 0.95
MIN_LOCATION_ACCURACY = 0.9   # measured 19/20 on 2026-11-18
MIN_RULE_COVERAGE = 0.95      # measured 100% on 2026-11-18
ALLOW_UNKNOWN_PRIMARY = False


def _labels() -> list[dict]:
    out = []
    for p in sorted(FIXTURES.glob("labels*.json")):
        out.extend(json.loads(p.read_text(encoding="utf-8")))
    return out


def test_labels_exist_and_valid():
    labels = _labels()
    assert len(labels) >= 20
    names = [l["file"] for l in labels]
    assert len(names) == len(set(names)), "a fixture is labelled twice"
    for l in labels:
        assert {"file", "category", "path", "line", "test", "origin", "note"} <= set(l), l
        assert l["category"] in CATEGORIES - {"unknown"}, l
        assert l["origin"] in ORIGINS, l
        assert l["line"] is None or (isinstance(l["line"], int) and l["line"] > 0), l
        assert l["path"] is None or "\\" not in l["path"], l
        assert l["note"], l


def test_every_label_has_a_file_and_every_fixture_a_label():
    labelled = {l["file"] for l in _labels()}
    on_disk = {p.name for p in FIXTURES.iterdir() if p.is_file() and not p.name.startswith("labels")}
    assert labelled - on_disk == set(), "labels without a fixture file"
    assert on_disk - labelled == set(), "fixture files without a label"


def test_real_logs_are_labelled_real():
    by_file = {l["file"]: l for l in _labels()}
    for name in ("gdh_pytest_docs_assert.log", "gdh_windows_path_assert.log"):
        assert by_file[name]["origin"] == "real-gdh-ci"


def test_fixtures_carry_no_local_identity():
    for p in FIXTURES.iterdir():
        if p.name.startswith(("tools_", "unity_", "infra_")) and p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            for bad in ("/Users/", "/private/tmp", "arshia"):
                assert bad not in text, (p.name, bad)


def _norm(path: str | None) -> str | None:
    return path.replace("\\", "/") if path else path


def test_fixture_accuracy():
    tr = pytest.importorskip("gamedevworkstation.features.triage_rules")
    labels = _labels()
    cat_ok = 0
    loc_total = loc_ok = 0
    rule_n = 0
    misses: list[str] = []
    unknowns: list[str] = []
    for l in labels:
        primary = tr.load(FIXTURES / l["file"]).primary
        got_cat = primary.category if primary else "unknown"
        got_file = _norm(primary.file) if primary else None
        got_line = primary.line if primary else None
        if primary is not None and primary.source == "rule":
            rule_n += 1
        if got_cat == "unknown":
            unknowns.append(l["file"])
        if got_cat == l["category"]:
            cat_ok += 1
        else:
            misses.append(f"CATEGORY {l['file']}: expected {l['category']}, got {got_cat}")
        if l["path"]:
            loc_total += 1
            if got_file == l["path"] and (l["line"] is None or got_line == l["line"]):
                loc_ok += 1
            else:
                misses.append(f"LOCATION {l['file']}: expected {l['path']}:{l['line']}, got {got_file}:{got_line}")
    n = len(labels)
    cat_acc = cat_ok / n
    loc_acc = loc_ok / loc_total if loc_total else 1.0
    coverage = rule_n / n
    print(f"ci_triage fixtures: {n} logs, category accuracy {cat_ok}/{n} ({cat_acc:.0%}), "
          f"location accuracy {loc_ok}/{loc_total} ({loc_acc:.0%}), rule coverage {coverage:.0%}")
    for m in misses:
        print("  miss:", m)
    import os
    report = os.environ.get("GDW_TRIAGE_REPORT")
    if report:
        Path(report).write_text(json.dumps({
            "logs": n, "category_correct": cat_ok, "category_accuracy": round(cat_acc, 4),
            "location_correct": loc_ok, "location_total": loc_total, "location_accuracy": round(loc_acc, 4),
            "rule_coverage": round(coverage, 4), "misses": misses}, indent=2), encoding="utf-8")
    assert cat_acc >= MIN_CATEGORY_ACCURACY, misses
    assert loc_acc >= MIN_LOCATION_ACCURACY, misses
    assert coverage >= MIN_RULE_COVERAGE
    if not ALLOW_UNKNOWN_PRIMARY:
        assert not unknowns, f"primary is unknown for {unknowns}"
