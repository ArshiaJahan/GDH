"""Config loading, data paths and API keys.

Config lives in TOML; keys come from the macOS Keychain (via `keyring`) or env vars,
never from config files, and are never logged.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import time
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

import tomli_w
from pydantic import BaseModel, Field, ValidationError, model_validator

log = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PACKAGE_DIR / "default_config.toml"
KEYRING_SERVICE = "Workspace"
PROVIDERS = ("anthropic", "openai", "elevenlabs")
ENV_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "elevenlabs": "ELEVENLABS_API_KEY"}


# ----------------------------------------------------------------------- paths


def data_dir() -> Path:
    if env := os.environ.get("WORKSPACE_HOME"):
        p = Path(env)
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "Workspace"
    else:
        p = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "workspace"
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    if env := os.environ.get("WORKSPACE_HOME"):
        p = Path(env) / "logs"
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Logs" / "Workspace"
    else:
        p = data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    return data_dir() / "config.toml"


def media_dir() -> Path:
    p = data_dir() / "media"
    p.mkdir(parents=True, exist_ok=True)
    return p


def sessions_dir() -> Path:
    p = data_dir() / "sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------- models


class LongContextPrice(BaseModel):
    threshold: int
    input: float
    output: float
    cache_write: float | None = None
    cache_read: float | None = None


def derive_display_name(model_id: str) -> str:
    """Readable name from a model ID, for models whose config has no `display_name`.

    'claude-opus-5-5' → 'Opus 5.5', 'gpt-6.1-sol' → 'GPT-6.1 Sol', 'scribe_v2' → 'Scribe v2';
    anything else is returned unchanged. Mirrored by shortModel in frontend/src/components/ui.tsx.
    """
    if m := re.match(r"^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?$", model_id):
        return f"{m[1].capitalize()} {m[2]}" + (f".{m[3]}" if m[3] else "")
    if m := re.match(r"^gpt-(\d+(?:\.\d+)?)(?:-([a-z0-9-]+))?$", model_id):
        rest = " ".join(w.capitalize() for w in m[2].split("-")) if m[2] else ""
        return f"GPT-{m[1]}" + (f" {rest}" if rest else "")
    if model_id in _ELEVEN_NAMES:
        return _ELEVEN_NAMES[model_id]
    if re.match(r"^(eleven|scribe|music)_[a-z0-9_]+$", model_id):  # eleven_flash_v2_5 → Eleven Flash v2.5
        s = re.sub(r"_v(\d+)(?:_(\d+))?(?=_|$)", lambda v: f" v{v[1]}" + (f".{v[2]}" if v[2] else ""), model_id)
        return " ".join(w if re.match(r"v\d", w) else w.capitalize() for w in re.split(r"[_ ]", s) if w)
    return model_id


# ElevenLabs models whose IDs don't read as their feature (frontend ui.tsx ELEVEN_NAMES mirrors this).
_ELEVEN_NAMES = {"eleven_text_to_sound_v3": "Sound Effects v3", "eleven_multilingual_sts_v2": "Voice Changer v2"}


class ModelConfig(BaseModel):
    id: str = ""
    display_name: str = ""  # shown in the UI; derived from the ID when the config leaves it out
    provider: str
    context_window: int = 200000
    max_output: int = 32000
    input: float = 0.0
    output: float = 0.0
    cache_write: float | None = None
    cache_read: float | None = None
    efforts: list[str] = Field(default_factory=lambda: ["low", "medium", "high"])
    no_thinking: str = ""
    vision: bool = True
    audio: bool = False
    long_context: LongContextPrice | None = None


class Config(BaseModel):
    orchestrator: dict[str, Any] = Field(default_factory=dict)
    accounts: dict[str, list[str]] = Field(default_factory=dict)
    tiers: dict[str, str] = Field(default_factory=dict)
    delegation: dict[str, Any] = Field(default_factory=dict)
    assistant: dict[str, Any] = Field(default_factory=dict)
    limits: dict[str, Any] = Field(default_factory=dict)
    elevenlabs: dict[str, Any] = Field(default_factory=dict)
    modes: dict[str, Any] = Field(default_factory=dict)
    data_policy: dict[str, Any] = Field(default_factory=dict)
    appearance: dict[str, Any] = Field(default_factory=dict)
    updates: dict[str, Any] = Field(default_factory=dict)
    sessions: dict[str, Any] = Field(default_factory=dict)
    mcp: dict[str, Any] = Field(default_factory=dict)      # [mcp.presets.<key>]: built-in MCP servers
    skills: dict[str, Any] = Field(default_factory=dict)   # disclosure, max_loaded, index_description_chars;
    #                                                        [skills.mcp_on_invoke]: skill → MCP servers it turns on
    hooks: dict[str, Any] = Field(default_factory=dict)    # enabled, gate_max_retries, gate_timeout_s, fail_open_notice
    ladder: dict[str, Any] = Field(default_factory=dict)   # visual_globs, critique_tier, critique_rounds, arbiter_tier
    campaigns: dict[str, Any] = Field(default_factory=dict)  # handoff, rollover_input_tokens, max_auto_turns, ...
    fleet: dict[str, Any] = Field(default_factory=dict)    # enabled, max_units, unit_timeout_min, relay_tokens
    models: dict[str, ModelConfig] = Field(default_factory=dict)

    def mcp_presets(self) -> dict[str, dict[str, Any]]:
        """Built-in MCP servers by server name (a preset's `name`, or its table key)."""
        out: dict[str, dict[str, Any]] = {}
        for key, p in ((self.mcp or {}).get("presets") or {}).items():
            if isinstance(p, dict):
                out[str(p.get("name") or key)] = {**p, "name": str(p.get("name") or key)}
        return out

    def skill_mcp_servers(self, skill: str) -> list[str]:
        """MCP servers that invoking `skill` turns on for the session ([skills.mcp_on_invoke])."""
        v = ((self.skills or {}).get("mcp_on_invoke") or {}).get(skill) or []
        return [v] if isinstance(v, str) else [str(x) for x in v]

    @model_validator(mode="after")
    def _fill_display_names(self) -> "Config":
        # Older config.toml files (and custom models) have no display_name.
        for mid, m in self.models.items():
            if not m.display_name:
                m.display_name = derive_display_name(mid)
        return self

    def model(self, model_id: str) -> ModelConfig:
        if model_id in self.models:
            return self.models[model_id]
        # Unknown model: guess provider from the name so it still works, unpriced.
        prov = "anthropic" if model_id.startswith("claude") else "openai"
        return ModelConfig(id=model_id, provider=prov, display_name=derive_display_name(model_id))

    def display_name(self, model_id: str) -> str:
        return self.model(model_id).display_name or derive_display_name(model_id)

    def label(self, model_id: str, tier: str | None = None) -> str:
        """UI label: 'GPT-6.1 Sol · codex.standard'. The tier defaults to the first one routing to the model."""
        tier = tier or self.tier_of(model_id)
        name = self.display_name(model_id)
        return f"{name} · {tier}" if tier else name

    def tier_models(self) -> dict[str, dict[str, str]]:
        """Each tier with the model it routes to, its display name and provider (for the UI)."""
        return {t: {"model": mid, "display_name": self.display_name(mid), "provider": self.model(mid).provider}
                for t, mid in self.tiers.items()}

    def resolve(self, tier_or_model: str) -> str:
        """`claude.fast` → model id; a model id passes through."""
        return self.tiers.get(tier_or_model, tier_or_model)

    def resolve_known(self, tier_or_model: str) -> str:
        """resolve() for user input: only tier keys and configured model ids (ValueError otherwise)."""
        if tier_or_model in self.tiers:
            return self.tiers[tier_or_model]
        if tier_or_model in self.models:
            return tier_or_model
        raise ValueError(f"Unknown model '{tier_or_model}'. Use a tier ({', '.join(self.tiers) or 'none set'}) "
                         f"or a configured model id ({', '.join(self.models) or 'none set'}).")

    def tier_of(self, model_id: str) -> str | None:
        for t, m in self.tiers.items():
            if m == model_id:
                return t
        return None

    def profiles(self, provider: str) -> list[str]:
        return self.accounts.get(provider) or ["default"]

    def profile_for(self, session: dict | None, provider: str) -> str:
        """The key profile a session uses for `provider`.

        Sessions keep their choices in settings.accounts ({anthropic, openai, elevenlabs}). Older
        sessions only have the `account` column, which always meant the Anthropic profile. A
        missing choice, or one naming a profile that no longer exists, falls back to the
        provider's default (its first profile in [accounts])."""
        profiles = self.profiles(provider)
        chosen = None
        if session:
            chosen = ((session.get("settings") or {}).get("accounts") or {}).get(provider)
            if chosen is None and provider == "anthropic":
                chosen = session.get("account")
        return chosen if chosen in profiles else profiles[0]

    def session_accounts(self, session: dict | None) -> dict[str, str]:
        """profile_for() for every provider."""
        return {p: self.profile_for(session, p) for p in PROVIDERS}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# The user's config.toml holds only overrides of the packaged defaults, marked with this version.
# Files without it are full copies of the defaults made by older versions (first run used to copy
# the whole file); they are slimmed down once (see _read_user).
CONFIG_FORMAT = 2
VERSION_KEY = "config_version"
USER_HEADER = ("# Your Workspace settings: only what differs from the built-in defaults (Settings writes here).\n"
               "# Everything else, including later changes to the defaults, comes from the app.\n"
               "# The defaults, with comments: config.example.toml in the source repository.\n\n")
_MISSING = object()
_load_error: dict[str, Any] | None = None
_invalid: dict[str, Any] | None = None  # settings ignored at the last load for having the wrong type
PRE_OVERRIDES_BACKUP = "config.toml.pre-overrides.bak"  # the old full copy, kept once and never overwritten
# Free-form sections (plain tables, not validated by the Config model): values whose default is a
# number, bool, string, list or table must have that type, else the default is used (see _check_types).
TYPED_SECTIONS = ("orchestrator", "delegation", "assistant", "limits", "elevenlabs", "modes", "data_policy",
                  "appearance", "updates", "sessions", "skills", "hooks", "ladder", "campaigns", "fleet")
# Tables inside typed sections that stay free-form (their entries may legitimately differ in type
# from the defaults: [skills.mcp_on_invoke] takes a server name or a list of them).
UNTYPED_KEYS = {"skills": ("mcp_on_invoke",)}


def load_error() -> dict[str, Any] | None:
    """Why config.toml was set aside at startup, or which of its settings were ignored (shown as a
    banner in the UI), or None."""
    return _load_error or _invalid


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _coerce(v: Any, d: Any) -> Any:
    """`v` as the type of its default `d`, or _MISSING when it can't be one. Numbers must be finite
    and not negative (every numeric setting is a count, size, time or amount); a number written
    as a string ("32000") is converted."""
    if _is_num(d):
        if isinstance(v, str):
            try:
                v = float(v.strip())
            except ValueError:
                return _MISSING
        if not _is_num(v) or v != v or v in (float("inf"), float("-inf")) or v < 0:
            return _MISSING
        return int(v) if isinstance(d, int) and float(v).is_integer() else float(v) if isinstance(d, float) else v
    if isinstance(d, bool):
        return v if isinstance(v, bool) else _MISSING
    for t in (str, list, dict):
        if isinstance(d, t):
            return v if isinstance(v, t) else _MISSING
    return v


def _check_types(user: dict, defaults: dict, prefix: str = "") -> tuple[dict, list[str]]:
    """`user` with values of the wrong type for their default dropped (numeric strings converted),
    and the dotted names of the dropped ones. Keys without a default pass unchecked."""
    out: dict[str, Any] = {}
    bad: list[str] = []
    for k, v in user.items():
        name = f"{prefix}{k}"
        d = defaults.get(k, _MISSING) if isinstance(defaults, dict) else _MISSING
        if d is _MISSING:
            out[k] = v
        elif isinstance(d, dict) and isinstance(v, dict):
            out[k], sub = _check_types(v, d, name + ".")
            bad += sub
        elif (c := _coerce(v, d)) is _MISSING:
            bad.append(name)
        else:
            out[k] = c
    return out, bad


def _split_invalid(user: dict, defaults: dict) -> tuple[dict, list[str]]:
    """(`user` without wrong-typed values in the free-form sections, their dotted names)."""
    out = dict(user)
    bad: list[str] = []
    for sec in TYPED_SECTIONS:
        if sec not in out:
            continue
        if not isinstance(out[sec], dict):
            bad.append(sec)
            del out[sec]
            continue
        d = defaults.get(sec, {})
        if sec in UNTYPED_KEYS and isinstance(d, dict):
            d = {k: v for k, v in d.items() if k not in UNTYPED_KEYS[sec]}
        out[sec], sub = _check_types(out[sec], d, sec + ".")
        bad += sub
    return out, bad


def invalid_settings(user: dict, defaults: dict | None = None) -> list[str]:
    """Dotted names of the settings in `user` (overrides or a Settings patch) with the wrong type."""
    return _split_invalid(user, _defaults() if defaults is None else defaults)[1]


def _drop_invalid(user: dict, defaults: dict, path: Path) -> dict:
    """The overrides without wrong-typed values in the free-form sections; those are listed in a
    banner (load_error) and left in the file for the user to fix. Clears the banner once they're gone."""
    global _invalid
    out, bad = _split_invalid(user, defaults)
    if not bad:
        _invalid = None
        return out
    if not _invalid or _invalid.get("keys") != bad:
        _invalid = {"message": f"Some settings in config.toml have a value of the wrong type, so their defaults are "
                               f"used: {', '.join(bad)}. Change them in Settings or fix them in the file.",
                    "error": f"{path}: {', '.join(bad)}", "keys": bad, "path": str(path), "at": time.time()}
        log.error("config.toml: ignored settings with a value of the wrong type: %s", ", ".join(bad))
    return out


def _overrides(user: dict, defaults: dict) -> dict:
    """The parts of `user` that differ from `defaults`, table by table."""
    out: dict[str, Any] = {}
    for k, v in user.items():
        d = defaults.get(k, _MISSING)
        if isinstance(v, dict) and isinstance(d, dict):
            if sub := _overrides(v, d):
                out[k] = sub
        elif d is _MISSING or v != d:
            out[k] = v
    return out


def _atomic_write(path: Path, text: str, *, backup: bool = True) -> None:
    """Write via a temporary file and rename, so a crash never leaves half a file. The previous
    version is kept as <name>.bak."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _dump_user(overrides: dict) -> str:
    body = {k: v for k, v in overrides.items() if k != VERSION_KEY}
    return USER_HEADER + tomli_w.dumps({VERSION_KEY: CONFIG_FORMAT, **body})


def _set_aside(path: Path, err: Exception) -> None:
    """config.toml can't be used: keep it as config.toml.broken-<time>, start a fresh one and
    remember why, so the UI can say so."""
    global _load_error
    broken = path.with_name(f"{path.name}.broken-{time.strftime('%Y%m%d-%H%M%S')}")
    os.replace(path, broken)
    _atomic_write(path, _dump_user({}), backup=False)
    detail = re.sub(r"\s+", " ", str(err)).strip()[:400]
    _load_error = {"message": f"Your config.toml couldn't be read, so Workspace started with the default settings. "
                              f"The file was kept as {broken.name} next to it.",
                   "error": detail, "path": str(path), "broken_path": str(broken), "at": time.time()}
    log.error("config.toml couldn't be read (%s); moved it to %s and started with the defaults", detail, broken)


def _defaults() -> dict:
    return tomllib.loads(DEFAULT_CONFIG_PATH.read_text())


def _read_user(path: Path, defaults: dict) -> tuple[dict, bool]:
    """(the user's overrides, whether the file is an old full copy to rewrite). Creates the file
    on first run and sets aside one that isn't valid TOML."""
    if not path.exists():
        _atomic_write(path, _dump_user({}), backup=False)
        return {}, False
    try:
        user = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        _set_aside(path, e)
        return {}, False
    version = user.pop(VERSION_KEY, None)
    if not isinstance(version, int) or version < CONFIG_FORMAT:
        # A full copy written by an older version. Every released default only ever added keys
        # (none changed value), so the defaults that wrote it equal today's on every key it has:
        # what matches them is dropped and future default changes reach this user; anything
        # the user changed stays.
        return _overrides(user, defaults), True
    return user, False


def load_config(path: Path | None = None) -> Config:
    """The packaged defaults with the user's overrides on top. A config.toml that can't be parsed
    or validated is set aside (see load_error) and the defaults are used, so the app still starts."""
    defaults = _defaults()
    path = path or config_path()
    user, legacy = _read_user(path, defaults)
    try:
        cfg = Config.model_validate(_deep_merge(defaults, _drop_invalid(user, defaults, path)))
    except ValidationError as e:
        _set_aside(path, e)
        cfg = Config.model_validate(defaults)
    else:
        if legacy:  # slim the old full copy down now that it's known to be good
            backup = path.with_name(PRE_OVERRIDES_BACKUP)  # the full original, kept once (.bak is replaced by every save)
            if not backup.exists():
                shutil.copy2(path, backup)
            _atomic_write(path, _dump_user(user))
            log.info("config.toml now holds only your changes (%d sections); the old full copy is %s",
                     len(user), backup.name)
    for mid, m in cfg.models.items():
        m.id = mid
    return cfg


def save_config_patch(patch: dict[str, Any], path: Path | None = None) -> Config:
    """Merge `patch` into the user's overrides, keep only what differs from the defaults, write
    the file atomically (previous version in config.toml.bak) and reload."""
    defaults = _defaults()
    path = path or config_path()
    current, _legacy = _read_user(path, defaults)
    _atomic_write(path, _dump_user(_overrides(_deep_merge(current, patch), defaults)))
    get_config.cache_clear()
    return get_config()


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config()


# ------------------------------------------------------------------------ keys


def _env_name(provider: str, profile: str) -> str:
    return f"WORKSPACE_KEY_{provider.upper()}_{profile.upper().replace('-', '_')}"


def get_key(provider: str, profile: str = "default") -> str | None:
    """Keychain first, then env. Never log the return value."""
    if v := os.environ.get(_env_name(provider, profile)):
        return v
    if os.environ.get("WORKSPACE_NO_KEYCHAIN") == "1":
        if v := _dev_keys().get(f"{provider}:{profile}"):
            return v
    else:
        try:
            import keyring

            if v := keyring.get_password(KEYRING_SERVICE, f"{provider}:{profile}"):
                return v
        except Exception:  # no keychain backend (Linux CI) — fall through to env
            pass
    if profile == "default":
        return os.environ.get(ENV_KEYS.get(provider, ""), None) or None
    return None


def _dev_keys_path() -> Path:
    return data_dir() / "dev-keys.json"


def _dev_keys() -> dict[str, str]:
    """DEVELOPMENT ONLY (WORKSPACE_NO_KEYCHAIN=1): provider keys saved from the UI live in
    <data_dir>/dev-keys.json (mode 0600, plain text) so dev runs and tests never touch the real
    Keychain yet a saved key still sticks. Never used when the Keychain is enabled."""
    try:
        d = json.loads(_dev_keys_path().read_text())
        return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_dev_keys(keys: dict[str, str]) -> None:
    p = _dev_keys_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(keys, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def set_key(provider: str, profile: str, key: str) -> None:
    if os.environ.get("WORKSPACE_NO_KEYCHAIN") == "1":  # dev/tests: a 0600 file under data_dir, never the Keychain
        _write_dev_keys({**_dev_keys(), f"{provider}:{profile}": key})
        return
    import keyring

    keyring.set_password(KEYRING_SERVICE, f"{provider}:{profile}", key)


def delete_key(provider: str, profile: str) -> None:
    if os.environ.get("WORKSPACE_NO_KEYCHAIN") == "1":  # tests and dev runs never touch the real Keychain
        keys = _dev_keys()
        if keys.pop(f"{provider}:{profile}", None) is not None:
            _write_dev_keys(keys)
        return
    import keyring

    try:
        keyring.delete_password(KEYRING_SERVICE, f"{provider}:{profile}")
    except Exception:
        pass


def keychain_enabled() -> bool:
    """False in development/tests (WORKSPACE_NO_KEYCHAIN=1): secrets then stay where they are, with a warning."""
    return os.environ.get("WORKSPACE_NO_KEYCHAIN") != "1"


def get_secret(account: str) -> str | None:
    """A Keychain entry of service `Workspace` by account name (e.g. `mcp:github:GITHUB_TOKEN`).
    None with WORKSPACE_NO_KEYCHAIN=1: tests and dev runs never read the real Keychain."""
    if not keychain_enabled():
        return None
    import keyring

    return keyring.get_password(KEYRING_SERVICE, account)


def set_secret(account: str, value: str) -> None:
    """Raises RuntimeError with WORKSPACE_NO_KEYCHAIN=1; callers check keychain_enabled() first and keep
    the value elsewhere (MCP servers store it in SQLite then)."""
    if not keychain_enabled():
        raise RuntimeError("The Keychain is disabled (WORKSPACE_NO_KEYCHAIN=1)")
    import keyring

    keyring.set_password(KEYRING_SERVICE, account, value)


def delete_secret(account: str) -> None:
    if not keychain_enabled():  # tests and dev runs never touch the real Keychain
        return
    import keyring

    try:
        keyring.delete_password(KEYRING_SERVICE, account)
    except Exception:  # already gone
        pass


def key_hint(key: str | None) -> str:
    """Safe display form of a key: last 4 chars only."""
    return f"…{key[-4:]}" if key else ""
