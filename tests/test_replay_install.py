"""Tests for replay_install.py: package status, install, upgrade consent, dry-run and the manifest
dependencies (regressions for M2/M3: a real `com.unity.test-framework` package, never a version
suffix; an upgrade path that can't be reached silently before is now reachable and refused without
consent; a non-Unity directory raises ValueError)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gamedevworkstation.features import replay_install as ri


@pytest.fixture
def proj(tmp_path):
    d = tmp_path / "Game"
    (d / "ProjectSettings").mkdir(parents=True)
    (d / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.21f1\n")
    (d / "Assets/Game").mkdir(parents=True)
    (d / "Packages").mkdir()
    (d / "Packages/manifest.json").write_text(json.dumps({"dependencies": {}}))
    return d.resolve()


def manifest(proj: Path) -> dict:
    return json.loads((proj / "Packages" / "manifest.json").read_text())


def write_installed_version(proj: Path, version: str) -> None:
    """Install the package, then rewrite package.json as a valid older version."""
    ri.install_replay_package(proj, allow_upgrade=True, allow_dependencies=True)
    pkg = proj / ri.PACKAGE_DIR / "package.json"
    pkg.write_text(json.dumps({"name": ri.PACKAGE_NAME, "version": version}, indent=2))


class TestReplayPackageStatus:
    def test_not_installed(self, proj):
        st = ri.replay_package_status(proj)
        assert st["installed"] is False
        assert not st["complete"]
        assert not st["modified"]
        assert set(st["missing_dependencies"]) == set(ri.MANIFEST_DEPENDENCIES)

    def test_installed_current(self, proj):
        d = proj / ri.PACKAGE_DIR
        d.mkdir(parents=True)
        (d / "package.json").write_bytes(ri._shipped()["package.json"])
        st = ri.replay_package_status(proj)
        assert st["installed"] is True
        assert st["version"] == ri.PACKAGE_VERSION
        assert not st["modified"]
        assert not st["outdated"]

    def test_modified_detected(self, proj):
        d = proj / ri.PACKAGE_DIR
        d.mkdir(parents=True)
        (d / "package.json").write_bytes(b"modified content")
        st = ri.replay_package_status(proj)
        assert st["installed"] is True
        # An unreadable package.json is never assumed to be an old version: never overwritten.
        assert "package.json" in st["modified"]
        assert not st["older"]

    def test_older_files_and_upgrade_consent(self, proj):
        write_installed_version(proj, "0.0.9")
        st = ri.replay_package_status(proj)
        assert st["outdated"] is True
        assert "package.json" in st["older"]
        assert st["needs_upgrade_consent"] is True
        assert not st["modified"]


class TestInstallReplayPackage:
    def test_dry_run_writes_nothing(self, proj):
        (proj / "Packages/manifest.json").write_text(json.dumps({"dependencies": {}}))
        result = ri.install_replay_package(proj, dry_run=True, allow_dependencies=True)
        assert result["ok"] is True
        assert result["status"] == "would_install"
        assert not (proj / ri.PACKAGE_DIR / "package.json").exists()
        assert manifest(proj) == {"dependencies": {}}

    def test_install_fresh(self, proj):
        result = ri.install_replay_package(proj, allow_upgrade=True)
        assert result["ok"] is True, result["message"]
        assert result["status"] == "installed"
        assert (proj / ri.PACKAGE_DIR / "package.json").is_file()
        assert (proj / ri.MARKER).is_file()

    def test_refuse_modified(self, proj):
        d = proj / ri.PACKAGE_DIR
        d.mkdir(parents=True)
        (d / "package.json").write_bytes(b"modified content")
        result = ri.install_replay_package(proj)
        assert result["ok"] is False
        assert result["status"] == "modified"
        assert (d / "package.json").read_bytes() == b"modified content"

    def test_already_installed(self, proj):
        ri.install_replay_package(proj, allow_upgrade=True)
        result = ri.install_replay_package(proj)
        assert result["ok"] is True
        assert result["status"] == "up_to_date"

    def test_upgrade_needs_consent_then_upgrades(self, proj):
        write_installed_version(proj, "0.0.9")
        refused = ri.install_replay_package(proj)
        assert refused["ok"] is False
        assert refused["status"] == "needs_upgrade_consent"
        # The old file is untouched until consent.
        assert json.loads((proj / ri.PACKAGE_DIR / "package.json").read_text())["version"] == "0.0.9"
        upgraded = ri.install_replay_package(proj, allow_upgrade=True)
        assert upgraded["ok"] is True
        assert upgraded["status"] == "upgraded"
        assert json.loads((proj / ri.PACKAGE_DIR / "package.json").read_text())["version"] == ri.PACKAGE_VERSION

    def test_never_downgrades(self, proj):
        write_installed_version(proj, "9.9.9")
        result = ri.install_replay_package(proj, allow_upgrade=True)
        assert result["ok"] is True
        assert result["status"] == "up_to_date"
        assert json.loads((proj / ri.PACKAGE_DIR / "package.json").read_text())["version"] == "9.9.9"

    def test_non_unity_project_raises(self, tmp_path):
        d = tmp_path / "not-unity"
        d.mkdir()
        with pytest.raises(ValueError):
            ri.install_replay_package(d)


class TestManifestDependencies:
    def test_adds_test_framework_as_its_own_package(self, proj):
        """M2: a real `com.unity.test-framework` dependency, never a `/test-framework` suffix."""
        ri.install_replay_package(proj, allow_upgrade=True, allow_dependencies=True)
        deps = manifest(proj)["dependencies"]
        assert deps["com.unity.test-framework"] == "1.6.0"
        assert deps["com.unity.inputsystem"] == "1.20.1"
        assert deps["com.unity.modules.physics"] == "1.0.0"
        assert deps["com.unity.modules.physics2d"] == "1.0.0"
        assert not any("/test-framework" in v for v in deps.values())
        assert "com.gdw.replay" in manifest(proj)["testables"]

    def test_preserves_existing_pins(self, proj):
        (proj / "Packages/manifest.json").write_text(json.dumps({"dependencies": {
            "com.unity.test-framework": "1.5.1",
            "com.unity.inputsystem": "1.9.0",
            "com.unity.modules.physics": "file:../local-physics",
        }}))
        ri.install_replay_package(proj, allow_upgrade=True, allow_dependencies=True)
        deps = manifest(proj)["dependencies"]
        assert deps["com.unity.test-framework"] == "1.5.1"
        assert deps["com.unity.inputsystem"] == "1.9.0"
        assert deps["com.unity.modules.physics"] == "file:../local-physics"
        assert deps["com.unity.modules.physics2d"] == "1.0.0"

    def test_manifest_untouched_without_consent(self, proj):
        """Project setup deps are only written with allow_dependencies (the setup consent)."""
        before = (proj / "Packages/manifest.json").read_text()
        result = ri.install_replay_package(proj, allow_upgrade=True)
        assert result["ok"] is True
        assert (proj / "Packages/manifest.json").read_text() == before
        assert "consent" in result["message"]

    def test_meta_written_for_testables_package(self, proj):
        ri.install_replay_package(proj, allow_upgrade=True, allow_dependencies=True)
        meta = proj / "Packages" / "com.gdw.replay" / "package.json.meta"
        assert meta.is_file()
        assert "guid:" in meta.read_text()


class TestHelperFunctions:
    def test_guid_is_deterministic(self):
        g1 = ri.guid_for("package.json")
        g2 = ri.guid_for("package.json")
        assert g1 == g2
        assert len(g1) == 32
        assert all(c in "0123456789abcdef" for c in g1)

    def test_guid_differs_by_path(self):
        assert ri.guid_for("package.json") != ri.guid_for("Runtime/GdwRandom.cs")

    def test_meta_text_contains_guid(self):
        text = ri.meta_text("package.json")
        assert "guid:" in text
        assert ri.guid_for("package.json") in text

    def test_version_tuple(self):
        assert ri._version_tuple("1.10.0") > ri._version_tuple("1.9.9")
        assert ri._version_tuple(None) == (0,)
