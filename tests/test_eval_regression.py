import json
from pathlib import Path

from gamedevworkstation.config import get_config
from gamedevworkstation.features import eval_fingerprint as fp
from gamedevworkstation.features import prompt_improver
from scripts import eval_regression


def _doc(fingerprint):
    doc = {"schema": 1, "fingerprint": fingerprint, "digest": fp.digest(fingerprint), "mode": "live",
           "ran_at": "2026-01-01T00:00:00Z", "git_sha": "abc", "model": "m", "calls": 2,
           "cost_usd": 0.1234, "summary": {"rate": 0.5, "nested": {"mean": 1.23456, "p95": 2.0}}}
    return doc


def _write_pair(path: Path, doc):
    path.mkdir(parents=True, exist_ok=True)
    (path / "prompt-improver.json").write_text(json.dumps(doc), encoding="utf-8")
    (path / "prompt-improver.md").write_text(fp.render_md(doc), encoding="utf-8")


def test_compute_and_diff_are_stable(tmp_path, monkeypatch):
    a = fp.compute(corpus_path=Path(prompt_improver.__file__).parents[3] / "tests/fixtures/prompt_improver/prompts.json")
    b = fp.compute(corpus_path=Path(prompt_improver.__file__).parents[3] / "tests/fixtures/prompt_improver/prompts.json")
    assert a == b
    assert set(a) == {"template_version", "prompt_sha256", "models", "settings", "corpus_sha256"}
    monkeypatch.setattr(prompt_improver, "EVAL_SYSTEM", prompt_improver.EVAL_SYSTEM + "x")
    c = fp.compute(corpus_path=Path(prompt_improver.__file__).parents[3] / "tests/fixtures/prompt_improver/prompts.json")
    assert a["prompt_sha256"] != c["prompt_sha256"]
    assert "prompt_sha256" in fp.diff(a, c)


def test_digest_config_model_and_diff(tmp_path):
    cfg = get_config()
    a = fp.compute(cfg)
    changed = cfg.model_copy(update={"prompt_improver": {**cfg.prompt_improver, "model": "another-model"}})
    b = fp.compute(changed)
    assert "models.prompt_improver" in fp.diff(a, b)
    assert fp.digest(a) == fp.digest(a)
    assert fp.diff(a, a) == []


def test_render_and_check_states(tmp_path):
    published_json, published_md = tmp_path / "prompt-improver.json", tmp_path / "prompt-improver.md"
    current = {"template_version": "x", "prompt_sha256": "a", "models": {"prompt_improver": "m"},
               "settings": {}, "corpus_sha256": "b"}
    assert fp.check(published_json, published_md, current)["status"] == "never_run"
    doc = _doc(current)
    md = fp.render_md(doc)
    assert md == fp.render_md(doc) and "1.235 / 2.000" in md
    assert "999999" not in md
    _write_pair(tmp_path, doc)
    assert fp.check(published_json, published_md, current)["status"] == "current"
    changed = {**current, "prompt_sha256": "different"}
    assert fp.check(published_json, published_md, changed)["status"] == "stale"
    published_md.write_text(md + "edited\n", encoding="utf-8")
    assert fp.check(published_json, published_md, current)["status"] == "invalid"
    published_md.write_text(md, encoding="utf-8")
    published_json.write_text("{", encoding="utf-8")
    assert fp.check(published_json, published_md, current)["status"] == "invalid"
    _write_pair(tmp_path, {**doc, "mode": "fake"})
    assert fp.check(published_json, published_md, current)["status"] == "invalid"
    published_json.unlink()
    _write_pair(tmp_path, doc)
    published_md.unlink()
    assert fp.check(published_json, published_md, current)["status"] == "invalid"


def test_cli_check_and_github_summary(tmp_path, monkeypatch, capsys):
    pub = tmp_path / "published"
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(eval_regression, "compute", lambda config=None: {"a": 1})
    assert eval_regression.main(["check", "--published-dir", str(pub)]) == 0
    doc = _doc({"a": 2})
    _write_pair(pub, doc)
    assert eval_regression.main(["check", "--published-dir", str(pub)]) == 0
    assert "stale" in capsys.readouterr().out
    assert eval_regression.main(["check", "--github", "--published-dir", str(pub)]) == 0
    assert "Prompt improver eval" in summary.read_text(encoding="utf-8")
    _write_pair(pub, {**doc, "digest": "bad"})
    assert eval_regression.main(["check", "--published-dir", str(pub)]) == 1
    try:
        eval_regression.main(["check", "--strict", "--published-dir", str(pub)])
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("--strict should be an unknown argument")


def test_cli_run_gates_and_publishes(tmp_path, monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert eval_regression.main(["run", "--out-dir", str(tmp_path)]) == 2
    monkeypatch.setenv("CI", "1")
    assert eval_regression.main(["run", "--approve-paid", "--out-dir", str(tmp_path)]) == 2
    monkeypatch.delenv("CI")
    monkeypatch.setattr(eval_regression, "compute", lambda config=None: {"a": 1})
    monkeypatch.setattr(eval_regression, "_run_live", lambda model: ({"rate": 0.5}, 3, 0.12))
    assert eval_regression.main(["run", "--approve-paid", "--out-dir", str(tmp_path)]) == 0
    assert (tmp_path / "prompt-improver.json").is_file()
    assert (tmp_path / "prompt-improver.md").is_file()
    assert eval_regression.main(["check", "--published-dir", str(tmp_path)]) == 0
