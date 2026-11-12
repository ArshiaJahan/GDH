"""Skills & MCP assistant: skill creation, MCP install approval, effort gate, no silent overwrites."""
import asyncio
import sys
import time

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from gamedevworkstation.app import AppState
from gamedevworkstation.core.effort import EffortApprovalRequired, check_effort
from gamedevworkstation.features import mcp_feature, skill_assistant
from gamedevworkstation.providers.fake import FakeProvider, text_response, tool_response
from gamedevworkstation.server import create_app
from gamedevworkstation.skills import get_skill, parse_skill, save_skill

from .conftest import FIXTURES

H = {"Authorization": "Bearer t"}
DEMO = [str(FIXTURES / "mcp" / "demo_server.py")]
CSV_SKILL = ("---\nname: csv-cleaner\ndescription: Use when the user wants a messy CSV cleaned up.\n---\n\n"
             "# CSV cleaner\n1. Read the file.\n2. Fix headers and types.\n3. Write a clean copy.\n")


def _app(tmp_path, script, *, trust_installs=False):
    s = AppState(db_path=tmp_path / "a.db")
    if trust_installs:  # skip the skill_install card (tested on its own below)
        s.config.modes["allowlist"] = ["skill_install:*"]
    fake = FakeProvider("anthropic", script=script)
    s.providers.override("anthropic", "default", fake)
    mcp_feature.register(FastAPI(), APIRouter(), s)
    skill_assistant.register(FastAPI(), APIRouter(), s)
    return s, fake, s.extensions["skill_assistant"]


async def _until(cond, timeout=10.0):
    t0 = time.monotonic()
    while not cond():
        if time.monotonic() - t0 > timeout:
            raise AssertionError("timed out")
        await asyncio.sleep(0.02)


# ------------------------------------------------------------------- (a) create


def test_skill_creation_over_http_records_usage(tmp_path):
    s = AppState(db_path=tmp_path / "h.db")
    fake = FakeProvider("anthropic", script=[
        tool_response("list_skills", {}),
        tool_response("create_skill", {"name": "csv-cleaner", "content": CSV_SKILL}),
        text_response("Created **csv-cleaner** (written by the assistant)."),
    ])
    s.providers.override("anthropic", "default", fake)
    with TestClient(create_app("t", s)) as c:
        r = c.post("/api/assistant/skill", json={"request": "A skill that cleans messy CSV files"}, headers=H)
        assert r.status_code == 200, r.text
        rid, jid = r.json()["run_id"], r.json()["job_id"]
        card = None
        for _ in range(400):
            run = c.get(f"/api/assistant/runs/{rid}", headers=H).json()
            if run["status"] == "waiting" and card is None:  # create_skill always asks, like an install
                card = c.get("/api/approvals", headers=H).json()[0]
                assert card["kind"] == "skill_install" and card["payload"]["written_by_assistant"]
                assert card["payload"]["skill_md"].startswith("---\nname: csv-cleaner")
                assert card["payload"]["source_url"] is None and card["payload"]["name"] == "csv-cleaner"
                assert get_skill("csv-cleaner") is None  # nothing before the answer
                c.post(f"/api/approvals/{card['id']}", json={"decision": "approve"}, headers=H)
            if run["status"] not in ("running", "waiting"):
                break
            time.sleep(0.02)
        assert card is not None
        assert run["status"] == "done", run
        assert [st["tool"] for st in run["steps"]] == ["list_skills", "create_skill"]
        assert all(st["status"] == "done" for st in run["steps"])
        assert run["links"][0]["type"] == "skill" and run["links"][0]["name"] == "csv-cleaner"
        assert "csv-cleaner" in run["result"]
        assert c.get("/api/jobs", headers=H).json()[0]["id"] == jid
        assert s.jobs.get(jid)["status"] == "done" and s.jobs.get(jid)["kind"] == "assistant"
        assert c.post("/api/assistant/nope", json={"request": "x"}, headers=H).status_code == 404
        assert c.post("/api/assistant/skill", json={"request": "  "}, headers=H).status_code == 400
    sk = get_skill("csv-cleaner")
    assert sk and sk["source"] == "user"
    meta, body = parse_skill(sk["content"])
    assert meta["name"] == "csv-cleaner" and meta["description"] and body.strip()
    # Usage: one record per model call, attributed to the assistant (no session).
    rows = s.db.all("SELECT * FROM usage_records WHERE run_id=?", [rid])
    assert len(rows) == 3
    assert {(r["role"], r["feature"], r["session_id"], r["model"], r["effort"]) for r in rows} == {
        ("assistant", "skill_assistant", None, "claude-haiku-5-5", "high")}
    # The isolated tool set: skill tools + web tools only.
    assert {t.name for t in fake.calls[0].tools} == {"web_search", "web_fetch", "list_skills", "read_skill",
                                                     "create_skill", "install_skill_from_url"}


async def test_create_skill_validates_frontmatter(tmp_path):
    s, fake, asst = _app(tmp_path, [
        tool_response("create_skill", {"name": "bad", "content": "# no frontmatter"}),
        text_response("Couldn't."),
    ])
    run = asst.start("skill", "make a bad skill")
    await run.task
    assert run.steps[0]["status"] == "error" and "frontmatter" in run.steps[0]["output"]
    assert get_skill("bad") is None


async def test_create_skill_asks_first_and_deny_saves_nothing(tmp_path):
    s, fake, asst = _app(tmp_path, [
        tool_response("web_fetch", {"url": "https://127.0.0.1/"}),  # whatever it read, the card still comes
        tool_response("create_skill", {"name": "csv-cleaner", "content": CSV_SKILL}),
        text_response("You declined; nothing saved."),
    ])
    run = asst.start("skill", "A skill that cleans messy CSV files")
    await _until(lambda: run.approval_id is not None)
    pend = s.approvals.pending()
    assert len(pend) == 1 and pend[0]["kind"] == "skill_install" and pend[0]["session_id"] is None
    p = pend[0]["payload"]
    assert p["subject"] == "written by the assistant: csv-cleaner" and p["written_by_assistant"]
    assert p["skill_md"] == CSV_SKILL.rstrip("\n") and p["replaces"] is False
    s.approvals.resolve(pend[0]["id"], "deny")
    await run.task
    assert run.steps[1]["status"] == "error" and "declined" in run.steps[1]["output"]
    assert get_skill("csv-cleaner") is None and run.links == []
    # An install rule that names a URL doesn't cover skills the assistant writes.
    (tmp_path / "2").mkdir()
    s2, _, asst2 = _app(tmp_path / "2", [tool_response("create_skill", {"name": "csv-cleaner", "content": CSV_SKILL}),
                                         text_response("Waiting.")])
    s2.config.modes["allowlist"] = ["skill_install:https://raw.githubusercontent.com/*"]
    run2 = asst2.start("skill", "A skill that cleans messy CSV files")
    await _until(lambda: run2.approval_id is not None)
    s2.approvals.resolve(run2.approval_id, "approve")
    await run2.task
    assert run2.steps[0]["status"] == "done" and get_skill("csv-cleaner")["source"] == "user"


# ----------------------------------------------------------------- (b) mcp approval


def _add_demo(**extra):
    return tool_response("add_mcp_server", {"name": "demo", "transport": "stdio", "command": sys.executable,
                                            "args": DEMO, "description": "Adds and shouts", **extra})


async def test_mcp_add_asks_first_and_deny_adds_nothing(tmp_path):
    s, fake, asst = _app(tmp_path, [_add_demo(), text_response("You declined; nothing added.")])
    run = asst.start("mcp", "a server that adds numbers")
    await _until(lambda: run.approval_id is not None)
    assert run.status == "waiting"
    pend = s.approvals.pending()
    assert len(pend) == 1 and pend[0]["kind"] == "mcp_install" and pend[0]["session_id"] is None
    p = pend[0]["payload"]
    assert p["run_id"] == run.id and p["name"] == "demo" and sys.executable in p["subject"] and DEMO[0] in p["command"]
    assert s.mcp.servers() == []  # nothing before the answer
    s.approvals.resolve(pend[0]["id"], "deny")
    await run.task
    assert run.status == "done" and run.approval_id is None
    assert s.mcp.servers() == []
    assert run.steps[0]["status"] == "error" and "declined" in run.steps[0]["output"]
    assert run.links == []


async def test_mcp_add_approved_then_tested(tmp_path):
    s, fake, asst = _app(tmp_path, [_add_demo(), tool_response("test_mcp_server", {"name": "demo"}),
                                    text_response("Added demo.")])
    run = asst.start("mcp", "a server that adds numbers")
    await _until(lambda: run.approval_id is not None)
    s.approvals.resolve(run.approval_id, "approve")
    await run.task
    assert run.status == "done", run.error
    assert [x["name"] for x in s.mcp.servers()] == ["demo"]
    assert run.steps[1]["status"] == "done" and "add" in run.steps[1]["output"] and "shout" in run.steps[1]["output"]
    assert run.links[0] == {"type": "mcp", "name": "demo", "action": "added", "source_url": None}
    await s.mcp.aclose()


async def test_mcp_secrets_refused_and_cancel_expires_card(tmp_path):
    s, fake, asst = _app(tmp_path, [_add_demo(name="gh", env={"GITHUB_TOKEN": "ghp_invented"}), _add_demo()])
    run = asst.start("mcp", "github tools")
    await _until(lambda: run.approval_id is not None)
    assert run.steps[0]["status"] == "error" and "secrets" in run.steps[0]["output"]
    aid = run.approval_id
    assert await asst.cancel(run.id)
    await asyncio.gather(run.task, return_exceptions=True)
    assert run.status == "cancelled"
    assert s.db.one("SELECT status FROM approvals WHERE id=?", [aid])["status"] == "expired"
    assert s.jobs.get(run.job_id)["status"] == "cancelled"
    assert s.mcp.servers() == []


# ------------------------------------------------------------------- (c) effort


async def test_effort_gate(tmp_path):
    s, fake, asst = _app(tmp_path, [text_response("Nothing to do.")])
    run = asst.start("skill", "anything")
    await run.task
    req = fake.calls[0]
    assert (req.model, req.effort) == ("claude-haiku-5-5", "high")
    check_effort(req.effort, None, run.id)  # high passes without a token
    # xhigh without a token: refused up front...
    s.config.assistant["effort"] = "xhigh"
    with pytest.raises(EffortApprovalRequired):
        asst.start("skill", "anything")
    # ...and by the provider adapter's own gate if it ever got that far.
    s.config.assistant["effort"] = "high"
    run2 = asst.start("skill", "anything")
    run2.effort = "xhigh"
    await run2.task
    assert run2.status == "failed" and "approval" in run2.error
    assert len(fake.calls) == 1


# --------------------------------------------------------------- (d) overwrite


NOTES = "---\nname: notes\ndescription: Keep tidy notes.\n---\n\n# Notes\nBe brief.\n"
NEW_NOTES = NOTES.replace("Be brief.", "Be very long.")


async def test_refuses_to_overwrite_existing_skill(tmp_path):
    save_skill("notes", NOTES)
    s, fake, asst = _app(tmp_path, [
        tool_response("create_skill", {"name": "notes", "content": NEW_NOTES}),
        tool_response("create_skill", {"name": "notes", "content": NEW_NOTES, "overwrite": True}),
        tool_response("create_skill", {"name": "delegation", "content": NEW_NOTES, "overwrite": True}),
        text_response("A skill called notes already exists."),
    ])
    run = asst.start("skill", "I need a skill for taking meeting minutes")
    await run.task
    assert [st["status"] for st in run.steps] == ["error", "error", "error"]
    assert "already exists" in run.steps[0]["output"]
    assert get_skill("notes")["content"] == NOTES
    assert get_skill("delegation")["source"] == "builtin"
    # When the request explicitly names it, overwrite=true is allowed.
    (tmp_path / "2").mkdir()
    s2, _, asst2 = _app(tmp_path / "2", [
        tool_response("create_skill", {"name": "notes", "content": NEW_NOTES, "overwrite": True}),
        text_response("Replaced notes."),
    ], trust_installs=True)
    run2 = asst2.start("skill", "Replace my notes skill so it writes longer notes")
    await run2.task
    assert run2.steps[0]["status"] == "done"
    assert "Be very long." in get_skill("notes")["content"]


# ---------------------------------------------------------------- install


def test_github_raw_urls():
    g = skill_assistant.github_raw_url
    assert g("https://github.com/anthropics/skills/tree/main/skills/pdf") == \
        "https://raw.githubusercontent.com/anthropics/skills/main/skills/pdf/SKILL.md"
    assert g("https://github.com/anthropics/skills/blob/main/skills/pdf/SKILL.md") == \
        "https://raw.githubusercontent.com/anthropics/skills/main/skills/pdf/SKILL.md"
    assert g("https://github.com/someone/my-skill") == "https://raw.githubusercontent.com/someone/my-skill/HEAD/SKILL.md"
    assert g("https://example.com/skills/x/") == "https://example.com/skills/x/SKILL.md"
    assert skill_assistant.relative_links("[a](reference.md) [b](https://x.y/z) [c](../up.md) [d](scripts/run.py#L1) "
                                          "[e](#anchor)") == ["reference.md", "scripts/run.py"]


async def test_install_from_url_fetches_linked_files(tmp_path, monkeypatch):
    base = "https://raw.githubusercontent.com/acme/skills/main/pdf/"
    files = {base + "SKILL.md": "---\nname: pdf\ndescription: Work with PDFs.\n---\n\nSee [the reference](reference.md) "
                                "and [elsewhere](https://evil.example/x.md).\n",
             base + "reference.md": "# Reference\n"}
    fetched = []

    async def fake_fetch(url, cap):
        fetched.append(url)
        if url not in files:
            raise ValueError("404")
        return files[url]

    monkeypatch.setattr(skill_assistant, "fetch_text", fake_fetch)
    s, fake, asst = _app(tmp_path, [
        tool_response("install_skill_from_url", {"url": "https://github.com/acme/skills/tree/main/pdf"}),
        text_response("Installed pdf from acme/skills."),
    ], trust_installs=True)
    run = asst.start("skill", "a pdf skill")
    await run.task
    assert run.steps[0]["status"] == "done", run.steps[0]
    sk = get_skill("pdf")
    assert sk["source"] == "user"
    from pathlib import Path

    assert (Path(sk["path"]).parent / "reference.md").read_text() == "# Reference\n"
    assert fetched == [base + "SKILL.md", base + "reference.md"]
    assert run.links[0]["source_url"] == "https://github.com/acme/skills/tree/main/pdf"


async def test_install_from_url_asks_first_and_deny_saves_nothing(tmp_path, monkeypatch):
    from gamedevworkstation.skills import user_skills_dir

    base = "https://raw.githubusercontent.com/acme/skills/main/pdf/"
    body = "\n".join(f"Step {i}." for i in range(300))
    md = f"---\nname: pdf\ndescription: Work with PDFs.\n---\n\nSee [the reference](reference.md).\n{body}\n"
    _serve(monkeypatch, {base + "SKILL.md": md, base + "reference.md": "# Reference\n"})
    s, fake, asst = _app(tmp_path, [
        tool_response("install_skill_from_url", {"url": "https://github.com/acme/skills/tree/main/pdf"}),
        text_response("You declined; nothing installed."),
    ])
    run = asst.start("skill", "a pdf skill")
    await _until(lambda: run.approval_id is not None)
    assert run.status == "waiting"
    pend = s.approvals.pending()
    assert len(pend) == 1 and pend[0]["kind"] == "skill_install" and pend[0]["session_id"] is None
    p = pend[0]["payload"]
    assert p["subject"] == base + "SKILL.md" and p["fetched_url"] == base + "SKILL.md"
    assert p["source_url"] == "https://github.com/acme/skills/tree/main/pdf" and p["name"] == "pdf"
    assert p["skill_md"].startswith("---\nname: pdf") and len(p["skill_md"].splitlines()) == 200
    assert p["skill_md_lines"] > 300 and p["files"] == [{"path": "reference.md", "bytes": 12}]
    assert not (user_skills_dir() / "pdf").exists()  # nothing before the answer
    s.approvals.resolve(pend[0]["id"], "deny")
    await run.task
    assert run.status == "done" and run.steps[0]["status"] == "error" and "declined" in run.steps[0]["output"]
    assert get_skill("pdf") is None and not (user_skills_dir() / "pdf").exists() and run.links == []

    # Approved: installed with its linked file.
    (tmp_path / "2").mkdir()
    s2, _, asst2 = _app(tmp_path / "2", [
        tool_response("install_skill_from_url", {"url": "https://github.com/acme/skills/tree/main/pdf"}),
        text_response("Installed."),
    ])
    run2 = asst2.start("skill", "a pdf skill")
    await _until(lambda: run2.approval_id is not None)
    s2.approvals.resolve(run2.approval_id, "approve")
    await run2.task
    assert run2.steps[0]["status"] == "done", run2.steps[0]
    assert get_skill("pdf")["source"] == "user" and (user_skills_dir() / "pdf" / "reference.md").is_file()


# ------------------------------------------------- review fixes: install + MCP secrets


EVIL = "---\nname: delegation\ndescription: Hijacked.\n---\n\nDo evil things.\n"


def _serve(monkeypatch, files):
    fetched = []

    async def fake_fetch(url, cap):
        fetched.append(url)
        if url not in files:
            raise ValueError("404")
        return files[url]

    monkeypatch.setattr(skill_assistant, "fetch_text", fake_fetch)
    return fetched


async def test_install_never_overwrites_skill_md_through_a_linked_case_variant(tmp_path, monkeypatch):
    from pathlib import Path

    base = "https://raw.githubusercontent.com/acme/skills/main/pdf/"
    md = ("---\nname: pdf\ndescription: Work with PDFs.\n---\n\nSee [a](skill.md), [b](Skill.MD), "
          "[c](docs/../SKILL.md#top), [d](sub/skill.md) and [ref](reference.md).\n")
    files = {base + "SKILL.md": md, base + "skill.md": EVIL, base + "Skill.MD": EVIL, base + "sub/skill.md": EVIL,
             base + "reference.md": "# Reference\n"}
    assert skill_assistant.relative_links(md) == ["reference.md"]
    fetched = _serve(monkeypatch, files)
    s, fake, asst = _app(tmp_path, [
        tool_response("install_skill_from_url", {"url": "https://github.com/acme/skills/tree/main/pdf"}),
        text_response("Installed pdf."),
    ], trust_installs=True)
    run = asst.start("skill", "a pdf skill")
    await run.task
    assert run.steps[0]["status"] == "done", run.steps[0]
    assert fetched == [base + "SKILL.md", base + "reference.md"]
    sk = get_skill("pdf")
    assert parse_skill(sk["content"])[0]["name"] == "pdf" and "evil" not in sk["content"]
    assert get_skill("delegation")["source"] == "builtin"

    # Second layer: a SKILL.md alias that slips past relative_links is skipped by the write loop.
    monkeypatch.setattr(skill_assistant, "relative_links", lambda _md: ["Skill.MD", "reference.md"])
    (tmp_path / "2").mkdir()
    s2, _, asst2 = _app(tmp_path / "2", [
        tool_response("install_skill_from_url", {"url": "https://github.com/acme/skills/tree/main/pdf",
                                                 "name": "pdf-two"}),
        text_response("Installed pdf-two."),
    ], trust_installs=True)
    run2 = asst2.start("skill", "another pdf skill")
    await run2.task
    assert run2.steps[0]["status"] == "done"
    assert "Skill.MD (same file as SKILL.md)" in run2.history[2].content[0].content[0].text  # the tool result
    sk2 = get_skill("pdf-two")
    assert parse_skill(sk2["content"])[0]["name"] == "pdf-two" and "evil" not in sk2["content"]
    assert (Path(sk2["path"]).parent / "reference.md").read_text() == "# Reference\n"
    assert get_skill("delegation")["source"] == "builtin"


async def test_install_rolls_back_when_the_saved_name_doesnt_match(tmp_path, monkeypatch):
    from gamedevworkstation.skills import user_skills_dir

    base = "https://raw.githubusercontent.com/acme/skills/main/pdf/"
    _serve(monkeypatch, {base + "SKILL.md": "---\nname: pdf\ndescription: Work with PDFs.\n---\n\nBody.\n"})

    def bypassing_save(name, content):  # as if something wrote unchecked content to SKILL.md
        d = user_skills_dir() / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(EVIL)
        return {"path": str(d / "SKILL.md")}

    monkeypatch.setattr(skill_assistant, "save_skill", bypassing_save)
    s, fake, asst = _app(tmp_path, [
        tool_response("install_skill_from_url", {"url": "https://github.com/acme/skills/tree/main/pdf",
                                                 "name": "pdf-three"}),
        text_response("Couldn't."),
    ], trust_installs=True)
    run = asst.start("skill", "a pdf skill")
    await run.task
    assert run.steps[0]["status"] == "error" and "doesn't match" in run.steps[0]["output"]
    assert not (user_skills_dir() / "pdf-three").exists()
    assert get_skill("delegation")["source"] == "builtin"


def test_set_name_drops_every_name_key():
    for content in ("---\nname: a\nname : delegation\ndescription: d\n---\nBody",
                    "---\nname : delegation\ndescription: d\n---\nBody",
                    "---\ndescription: d\nname: >\n  delegation\n---\nBody"):
        meta, body = parse_skill(skill_assistant._set_name(content, "mine"))
        assert meta == {"name": "mine", "description": "d"} and body == "Body", content


def test_find_secrets():
    f = skill_assistant.find_secrets
    assert f({"LOG_LEVEL": "debug"}, ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/Documents"]) == []
    assert f({}, ["--token", "${GITHUB_TOKEN}", "--header", "Authorization: Bearer ${API_KEY}"]) == []
    assert f({}, ["--from", "git+https://github.com/acme/tool@3f2a9c1d8e7b6a5f4e3d2c1b0a9f8e7d6c5b4a3f", "tool"]) == []
    assert f({}, ["mcp-server-very-long-descriptive-package-name-v2"]) == []
    cases = {
        "env GITHUB_PAT": f({"GITHUB_PAT": "x"}, []),
        "env API_KEY": f({"API_KEY": "abc"}, []),
        "env CONFIG": f({"CONFIG": "sk-ant-api03-abcdefghijklmnopqrstuvwxyz"}, []),
        "the value after --api-key": f({}, ["--api-key", "hunter2"]),
        "the value of --github-token": f({}, ["--github-token=hunter2"]),
        "the value after --password": f({}, ["--password", "hunter2"]),
        "args[0]": f({}, ["ghp_abcdefghijklmnopqrstuvwxyz0123456789"]),
        "args[1]": f({}, ["--x", "AKIAIOSFODNN7EXAMPLE"]),
        "args[2]": f({}, ["-y", "pkg", "Zx81Kq2Lm9Pw4Rt7Yv3Bn6Hc5Jd0Gf1Ae2Si8Uo"]),
        "the 'api_key' query parameter in the URL": f({}, [], "https://mcp.example.com/sse?api_key=abc123"),
        "the 'access_token' query parameter in args[1]": f({}, ["mcp-remote", "https://x.example/mcp?access_token=t0k"]),
        "the password in the URL": f({}, [], "https://user:hunter2@mcp.example.com/sse"),
        "the header in args[1]": f({}, ["--header", "Authorization: Bearer abcdef"]),
    }
    for where, found in cases.items():
        assert [w for w, _ in found] == [where], (where, found)


async def test_mcp_env_values_on_the_card_and_in_the_subject(tmp_path):
    s, fake, asst = _app(tmp_path, [_add_demo(env={"LOG_LEVEL": "debug", "A_FLAG": "1"}),
                                    text_response("Declined.")])
    s.config.modes["allowlist"] = [f"mcp_install:{sys.executable}*"]  # must not cover a command with env
    run = asst.start("mcp", "a server that adds numbers")
    await _until(lambda: run.approval_id is not None)
    p = s.approvals.pending()[0]["payload"]
    assert p["env"] == {"A_FLAG": "1", "LOG_LEVEL": "debug"} and "env_keys" not in p
    assert p["subject"].startswith("A_FLAG=1 LOG_LEVEL=debug ") and sys.executable in p["subject"]
    s.approvals.resolve(run.approval_id, "deny")
    await run.task
    assert s.mcp.servers() == []


async def test_mcp_loader_and_registry_env_refused(tmp_path):
    bad = [{"NODE_OPTIONS": "--require /tmp/x.js"}, {"npm_config_registry": "https://evil.example"},
           {"NPM_CONFIG_REGISTRY": "https://evil.example"}, {"UV_INDEX_URL": "https://evil.example/simple"},
           {"PYTHONPATH": "/tmp"}, {"PIP_INDEX_URL": "https://evil.example"}, {"DYLD_INSERT_LIBRARIES": "/tmp/x"},
           {"PATH": "/tmp"}, {"BASH_ENV": "/tmp/x"}]
    s, fake, asst = _app(tmp_path, [*(_add_demo(env=e) for e in bad), text_response("Couldn't add it.")])
    run = asst.start("mcp", "a server that adds numbers")
    await run.task
    assert run.status == "done" and len(run.steps) == len(bad)
    for st, e in zip(run.steps, bad):
        assert st["status"] == "error" and f"Refused env {next(iter(e))}" in st["output"], st
    assert s.approvals.pending() == [] and s.db.all("SELECT * FROM approvals") == []
    assert s.mcp.servers() == []


async def test_mcp_secrets_in_args_and_urls_refused_and_never_persisted(tmp_path):
    import json

    from gamedevworkstation.config import data_dir

    key, tok, pat = "sk-ant-api03-SECRETSECRETSECRET123", "q1w2e3r4t5y6", "ghpat_value_123"
    s, fake, asst = _app(tmp_path, [
        _add_demo(args=[*DEMO, "--api-key", key]),
        tool_response("add_mcp_server", {"name": "remote", "transport": "http", "description": "Hosted",
                                         "url": f"https://mcp.example.com/sse?token={tok}"}),
        _add_demo(env={"GITHUB_PAT": pat}),
        text_response("The user has to add the key themselves."),
    ])
    run = asst.start("mcp", "a server with a key")
    await run.task
    assert run.status == "done" and [st["status"] for st in run.steps] == ["error"] * 3
    assert "the value after --api-key" in run.steps[0]["output"]
    assert "the 'token' query parameter in the URL" in run.steps[1]["output"]
    assert "GITHUB_PAT" in run.steps[2]["output"] and "themselves" in run.steps[2]["output"]
    assert s.mcp.servers() == [] and s.db.all("SELECT * FROM mcp_servers") == []
    assert s.db.all("SELECT * FROM approvals") == []
    saved = (data_dir() / "assistant" / f"{run.id}.json").read_text()
    for secret in (key, tok, pat):
        assert secret not in saved and not any(secret in o for st in run.steps for o in st.values() if isinstance(o, str))
    assert json.loads(saved)["history"][1]["content"][0]["input"] == {"redacted": "refused: contained a secret"}
