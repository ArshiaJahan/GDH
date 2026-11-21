"""Upgrades preserve the ledger independently of trace capture and routing."""
import sqlite3
import tomllib
from pathlib import Path

from gamedevworkstation import config
from gamedevworkstation.db import DB, MIGRATIONS, SCHEMA, SCHEMA_VERSION


def test_v5_upgrade_preserves_usage_and_delegation_rows(tmp_path):
    path = tmp_path / "v5.db"
    with sqlite3.connect(path) as c:
        c.executescript(SCHEMA)
        for version, step in MIGRATIONS:
            if version <= 5:
                step(c)
        c.execute("PRAGMA user_version=5")
        c.execute("INSERT INTO usage_records (ts, provider, model, run_id, cost_usd, billing) "
                  "VALUES (1, 'anthropic', 'legacy', 'run-old', 0.25, 'api'), "
                  "(2, 'anthropic', 'legacy', 'run-subscription', 0.5, 'subscription')")
        c.execute("INSERT INTO delegation_stats (ts, job_type, provider, model, cost_usd, success) "
                  "VALUES (1, 'extract', 'anthropic', 'legacy', 0.25, 1)")
        c.row_factory = sqlite3.Row
        usage = [dict(row) for row in c.execute("SELECT * FROM usage_records ORDER BY id")]
        delegation = dict(c.execute("SELECT * FROM delegation_stats").fetchone())
    c.close()

    db = DB(path)
    try:
        assert db.user_version() == SCHEMA_VERSION == 6
        assert db.all("SELECT * FROM usage_records ORDER BY id") == [
            {**row, "task_id": None, "task_attribution": None} for row in usage
        ]
        assert db.one("SELECT * FROM delegation_stats") == {**delegation, "mixed_models": 0}
        indexes = {
            tuple(col["name"] for col in db.all(f"PRAGMA index_info('{index['name']}')"))
            for index in db.all("PRAGMA index_list('usage_records')")
        }
        assert ("task_id", "ts") in indexes
        assert ("run_id", "ts") in indexes
        mixed = next(col for col in db.all("PRAGMA table_info('delegation_stats')")
                     if col["name"] == "mixed_models")
        assert mixed["notnull"] == 1 and mixed["dflt_value"] == "0"
    finally:
        db.close()
    db = DB(path)
    try:
        assert db.user_version() == 6
        assert len(db.all("SELECT * FROM usage_records")) == 2
    finally:
        db.close()


def test_trace_and_routing_config_defaults_and_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_load_error", None)
    monkeypatch.setattr(config, "_invalid", None)
    path = tmp_path / "config.toml"
    defaults = config.load_config(path)
    assert defaults.tracing == {
        "enabled": True, "sample_rate": 1.0, "retention_days": 7, "max_spans": 100000,
        "otlp_endpoint": "", "otlp_timeout_s": 2.0, "otlp_headers_env": {},
    }
    assert defaults.model_routing == {
        "enabled": True, "max_escalations": 1, "revision": "1", "rules": {
            "extract": {"candidates": ["claude.fast", "claude.standard"], "check": "json_object"},
            "mechanical_edit": {"candidates": ["codex.fast", "codex.standard"], "check": "non_empty"},
            "implement_feature": {"candidates": ["codex.standard"], "check": "non_empty"},
        },
    }
    assert defaults.limits["task_usd"] == 0.0
    example = Path(__file__).resolve().parents[1] / "config.example.toml"
    example_config = tomllib.loads(example.read_text(encoding="utf-8"))
    assert example_config["tracing"] == defaults.tracing
    assert example_config["model_routing"] == defaults.model_routing

    path.write_text('config_version = 2\n[tracing]\nenabled = "yes"\nsample_rate = 2.0\n'
                    'retention_days = -1\nmax_spans = 100001\notlp_timeout_s = 0.0\n'
                    '[model_routing]\nmax_escalations = 0.5\n'
                    '[model_routing.rules.x]\ncandidates = ["codex.fast"]\ncheck = "non_empty"\n'
                    '[model_routing.rules.extract]\ncheck = { custom = true }\n', encoding="utf-8")
    loaded = config.load_config(path)
    assert loaded.tracing == defaults.tracing
    assert loaded.model_routing["max_escalations"] == 1
    assert loaded.model_routing["rules"]["x"] == {"candidates": ["codex.fast"], "check": "non_empty"}
    assert loaded.model_routing["rules"]["extract"]["check"] == {"custom": True}
    report = config.load_error()
    assert "wrong type" in report["message"]
    assert set(report["keys"]) == {
        "tracing.enabled", "tracing.sample_rate", "tracing.retention_days", "tracing.max_spans",
        "tracing.otlp_timeout_s", "model_routing.max_escalations",
    }
