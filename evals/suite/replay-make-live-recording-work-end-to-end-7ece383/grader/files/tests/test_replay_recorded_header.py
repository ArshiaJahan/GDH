"""What the C# recorder (com.gdw.replay 0.1.1) writes must be what the Python reader accepts.

The fixture is a real header from a recording made in Unity 6000.3.21f1. Before 0.1.1 the recorder wrote
empty strings for the content, lock, input and schema digests and dropped `unity.input` from the provider
list, so every live recording was rejected as incompatible.
"""
import copy
import json
import re
from pathlib import Path

import pytest

from gamedevworkstation.features import replay_format

FIXTURE = Path(__file__).parent / "fixtures" / "replay" / "recorded_0_1_1"
TEMPLATES = Path(__file__).resolve().parents[1] / "skills" / "replay" / "templates" / "com.gdw.replay"


def _header() -> dict:
    return json.loads((FIXTURE / "header.json").read_text(encoding="utf-8"))


def _frames() -> list[dict]:
    text = (FIXTURE / "frames_head.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_recorded_header_passes_the_reader():
    replay_format._check_header(_header())


def test_header_lists_exactly_the_providers_the_frames_hold():
    header_ids = sorted(p["id"] for p in _header()["providers"])
    for row in _frames():
        assert sorted(row["providers"]) == header_ids
    assert "unity.input" in header_ids


@pytest.mark.parametrize("path", [
    ("project", "content_sha256"),
    ("scene", "content_sha256"),
    ("packages", "lock_sha256"),
    ("input", "settings_sha256"),
])
def test_an_empty_digest_is_still_rejected(path):
    header = copy.deepcopy(_header())
    header[path[0]][path[1]] = ""
    with pytest.raises(replay_format.ReplayFormatError):
        replay_format._check_header(header)


def test_recorder_no_longer_writes_empty_digests():
    source = (TEMPLATES / "Runtime" / "ReplaySession.cs").read_text(encoding="utf-8")
    assert not re.search(r'(ContentSha256|LockSha256|SchemaSha256)\s*=\s*""', source)


def test_record_from_edit_mode_waits_for_play_mode():
    source = (TEMPLATES / "Editor" / "ReplayCommands.cs").read_text(encoding="utf-8")
    assert "EditorApplication.EnterPlaymode()" in source
    assert "PlayModeStateChange.EnteredPlayMode" in source
    assert "SessionState" in source
