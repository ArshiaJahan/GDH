import os
import tomllib

from gamedevworkstation.tool_policy import (
    SAFE_WHEN_BROKEN,
    PolicyHolder,
    ToolPolicy,
    default_policy_path,
    load_policy,
    validate,
)


def write_policy(path, text):
    path.write_text(text, encoding="utf-8")


def test_packaged_default_and_decisions():
    with default_policy_path().open("rb") as handle:
        data = tomllib.load(handle)
    assert validate(data) is data
    assert {"main", "claude_code", "subagent"} <= data["agents"].keys()
    policy = load_policy()
    for agent in ("main", "claude_code"):
        assert policy.decide(agent, "read_file").allowed
        assert policy.decide(agent, "run_command").allowed
        assert policy.decide(agent, "mcp__x__y").allowed
    assert policy.decide("subagent", "read_file").allowed
    assert policy.decide("subagent", "run_command").allowed
    denied = policy.decide("subagent", "mcp__github__get_issue")
    assert not denied.allowed and "mcp__*" in denied.reason
    for name in ("run_command", "write_file"):
        assert not policy.decide("subagent", name, job_type="extract").allowed
    assert policy.decide("subagent", "web_fetch", job_type="extract").allowed
    assert policy.decide("subagent", "run_command", job_type="mechanical_edit").allowed
    assert policy.decide("hook", "run_command").allowed
    assert not policy.decide("unknown", "read_file").allowed


def test_deny_wins_and_lists_replace(tmp_path):
    path = tmp_path / "tool_policy.toml"
    write_policy(path, 'version=1\n[agents.subagent]\nallow=["*"]\ndeny=["run_*"]\n')
    policy = load_policy(path)
    assert not policy.decide("subagent", "run_command").allowed
    write_policy(path, 'version=1\n[agents.subagent]\nallow=["read_file"]\n')
    policy = load_policy(path)
    assert policy.decide("subagent", "read_file").allowed
    assert not policy.decide("subagent", "run_command").allowed


def test_job_type_user_override_and_missing_user(tmp_path):
    assert load_policy(tmp_path / "missing.toml").decide("main", "run_command").allowed
    path = tmp_path / "policy.toml"
    write_policy(path, 'version=1\n[agents.subagent.job_types.extract]\nallow=["mcp__github__get_*"]\ndeny=[]\n')
    policy = load_policy(path)
    assert not policy.decide("subagent", "mcp__github__get_issue", job_type="extract").allowed  # agent level still denies mcp__*
    write_policy(path, 'version=1\n[agents.subagent]\nallow=["mcp__github__*", "read_file"]\ndeny=[]\n'
                       '[agents.subagent.job_types.extract]\nallow=["mcp__github__get_*"]\ndeny=[]\n')
    policy = load_policy(path)
    assert policy.decide("subagent", "mcp__github__get_issue", job_type="extract").allowed
    assert not policy.decide("subagent", "mcp__github__delete_repo", job_type="extract").allowed  # job type narrows
    assert policy.decide("subagent", "mcp__github__delete_repo", job_type="unknown_free_form").allowed  # agent level only


def test_job_type_never_widens_or_drops_agent_level_denies(tmp_path):
    path = tmp_path / "policy.toml"
    write_policy(path, 'version=1\n[agents.subagent]\nallow=["read_file", "write_file", "run_command"]\ndeny=["run_command"]\n'
                       '[agents.subagent.job_types.mechanical_edit]\nallow=["read_file", "write_file", "run_command", "delete_file"]\n'
                       'deny=[]\n')
    policy = load_policy(path)
    for job in ("mechanical_edit", "other", None):
        assert not policy.decide("subagent", "run_command", job_type=job).allowed, job  # agent deny holds for every job type
    assert not policy.decide("subagent", "delete_file", job_type="mechanical_edit").allowed  # job allow can't widen
    assert policy.decide("subagent", "write_file", job_type="mechanical_edit").allowed


def test_packaged_job_types_keep_their_grants():
    policy = load_policy()
    assert policy.filter_names("subagent", ["read_file", "run_command", "web_fetch", "mcp__x__y"], job_type="extract") == ["read_file", "web_fetch"]
    assert policy.filter_names("subagent", ["write_file", "run_command", "delete_file"], job_type="mechanical_edit") == ["write_file", "run_command"]
    assert policy.filter_names("subagent", ["write_file", "run_command", "delete_file", "unity"], job_type="implement_feature") == ["write_file", "run_command", "delete_file", "unity"]


def test_malformed_policy_fails_closed(tmp_path):
    examples = [
        "version = [\n",
        "version=1\nextra=1\n",
        'version=1\n[agents.unknown]\nallow=["*"]\n',
        "version=1\n[agents.main]\nallow='x'\n",
        'version=1\n[egress]\nextra_patterns=["["]\n',
        "version=2\n",
    ]
    for index, content in enumerate(examples):
        path = tmp_path / f"bad{index}.toml"
        write_policy(path, content)
        policy = load_policy(path)
        assert policy.broken and str(path) in policy.broken
        for tool in SAFE_WHEN_BROKEN:
            assert policy.decide("main", tool).allowed
        denied = policy.decide("main", "run_command")
        assert not denied.allowed and str(path) in denied.reason


def test_mcp_settings_and_egress_defaults(tmp_path):
    policy = load_policy()
    assert not policy.mcp_trust_read_only("arbitrary")
    assert not policy.mcp_trust_read_only("gdw")  # trust never comes from the name
    path = tmp_path / "policy.toml"
    write_policy(path, 'version=1\n[mcp.servers.mcpdemo]\ntrust_read_only_hint=true\n')
    assert load_policy(path).mcp_trust_read_only("mcpdemo")
    write_policy(path, 'version=1\n[mcp.servers.default]\ntrust_read_only_hint=true\n[mcp.servers.special]\ntrust_read_only_hint=false\n')
    policy = load_policy(path)
    assert policy.mcp_trust_read_only("other")
    assert not policy.mcp_trust_read_only("special")
    write_policy(path, "version=1\n[mcp]\n")
    assert not load_policy(path).mcp_trust_read_only("other")


def test_holder_reloads_changes_and_malformed_file(tmp_path):
    path = tmp_path / "policy.toml"
    write_policy(path, 'version=1\n[agents.main]\nallow=["read_file"]\n')
    holder = PolicyHolder(path)
    first = holder.current()
    assert first.decide("main", "run_command").allowed is False
    write_policy(path, 'version=1\n[agents.main]\nallow=["run_command"]\n')
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 2_000_000))
    second = holder.current()
    assert second is not first and second.decide("main", "run_command").allowed
    write_policy(path, "version = [\n")
    assert holder.current().broken


def test_fingerprint_is_stable_and_tracks_rules():
    data = load_policy().data
    one = ToolPolicy(data)
    two = ToolPolicy(data)
    assert one.fingerprint() == two.fingerprint()
    changed = {**data, "agents": {**data["agents"], "main": {"allow": ["read_file"], "deny": []}}}
    assert ToolPolicy(changed).fingerprint() != one.fingerprint()


def test_builtin_trust_is_not_granted_by_server_name():
    policy = load_policy()
    assert not policy.mcp_trust_read_only("gdw")
    assert policy.mcp_trust_read_only("gdw", builtin=True)
    assert not policy.mcp_trust_read_only("anything", builtin=False)


def test_claude_code_broken_refusal(tmp_path):
    path = tmp_path / "policy.toml"
    write_policy(path, "not = [valid")
    policy = load_policy(path)
    for tool in ("Write", "Edit", "Bash", "WebFetch", "Task"):
        assert "malformed" in policy.cc_broken_refusal(tool)
    for tool in ("Read", "Glob", "Grep", "LS"):
        assert policy.cc_broken_refusal(tool) is None
    assert load_policy().cc_broken_refusal("Write") is None
