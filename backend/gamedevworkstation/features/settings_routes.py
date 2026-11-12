"""Settings: account profiles and keys (Keychain), defaults, budgets, modes, data policy,
and Appearance backgrounds. Keys are written to the Keychain and never returned or logged."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Body, FastAPI, HTTPException, UploadFile

from ..config import (ENV_KEYS, PROVIDERS, Config, _env_name, data_dir, delete_key, get_config, get_key,
                      invalid_settings, key_hint, save_config_patch, set_key)

if TYPE_CHECKING:
    from ..app import AppState

EDITABLE = {"orchestrator", "tiers", "delegation", "limits", "elevenlabs", "modes", "data_policy", "appearance", "updates",
            "skills", "hooks", "ladder", "campaigns", "fleet", "unity", "claude_code"}
BG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".m4v", ".mov", ".webm"}


# Settings that take one of a few words (checked on PATCH; types are checked by invalid_settings).
CHOICES = {("skills", "disclosure"): ("progressive", "full"), ("campaigns", "handoff"): ("per_phase", "on_cost"),
           ("unity", "backend"): ("auto", "mcp", "cli"), ("unity", "eval"): ("ask", "off"),
           ("unity", "clone_when_open"): ("ask", "never", "always"), ("unity", "harness_scripts"): ("ask", "never")}


# Sections that never change which keys, profiles or models the providers use: saving only
# these keeps the provider clients (and their connection pools) as they are.
NO_PROVIDER_RESET = {"appearance", "skills", "hooks", "ladder", "campaigns", "fleet", "unity", "claude_code"}


def _apply(app: "AppState", new: Config, reset_providers: bool = True) -> None:
    """Update the shared Config object in place so every service sees the change."""
    for f in Config.model_fields:
        setattr(app.config, f, getattr(new, f))
    if not reset_providers:
        return
    app.providers.reset()
    el = app.extensions.get("elevenlabs")
    if el is not None:
        el.clients.clear()  # type: ignore[attr-defined]


async def _keys_changed(app: "AppState", provider: str) -> None:
    """After a key or profile change: drop cached clients and re-run that provider's auth checks,
    so My usage and the model list reflect it at once."""
    app.providers.reset()
    el = app.extensions.get("elevenlabs")
    if el is not None:
        el.clients.clear()  # type: ignore[attr-defined]
    st = app.extensions.get("status")
    if st is not None:
        await st.check_all(only=provider)  # type: ignore[attr-defined]


def _forget_profiles(app: "AppState", provider: str, gone: list[str]) -> None:
    """Profiles removed from [accounts]: delete their Keychain keys and auth rows. Sessions that
    chose one fall back to the provider's default (Config.profile_for)."""
    for prof in gone:
        delete_key(provider, prof)
        app.db.execute("DELETE FROM auth_status WHERE provider=? AND profile=?", [provider, prof])


def _key_source(provider: str, profile: str) -> str | None:
    if os.environ.get(_env_name(provider, profile)) or (profile == "default" and os.environ.get(ENV_KEYS[provider])):
        return "environment"
    return "keychain" if get_key(provider, profile) else None


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    @api.get("/settings")
    async def settings() -> dict:
        c = S.config
        accounts = {}
        for p in PROVIDERS:
            accounts[p] = [{"profile": prof, "has_key": bool(k := get_key(p, prof)), "hint": key_hint(k),
                            "source": _key_source(p, prof)} for prof in c.profiles(p)]
        return {**{k: getattr(c, k) for k in EDITABLE}, "accounts": accounts,
                "models": {k: v.model_dump() for k, v in c.models.items()}, "tier_models": c.tier_models(),
                "config_path": str(data_dir() / "config.toml")}

    @api.get("/setup")
    async def setup_status() -> dict:
        """The first-run checklist on the empty chat: which steps are done."""
        keys = {p: any(get_key(p, prof) for prof in S.config.profiles(p)) for p in PROVIDERS}
        return {
            "keys": keys,
            "folder": bool(S.db.one("SELECT 1 FROM sessions WHERE folder IS NOT NULL LIMIT 1")),
            "skill": bool(S.db.one("SELECT 1 FROM messages WHERE instr(meta, '\"invoked_skill\"') > 0 LIMIT 1")),
        }

    @api.patch("/settings")
    async def patch_settings(body: dict = Body(...)) -> dict:
        bad = set(body) - EDITABLE
        if bad:
            raise HTTPException(400, f"Not editable here: {', '.join(sorted(bad))}")
        if bad_types := invalid_settings(body):
            raise HTTPException(400, f"Wrong type of value for: {', '.join(bad_types)}")
        for (sec, key), allowed in CHOICES.items():
            v = (body.get(sec) or {}).get(key) if isinstance(body.get(sec), dict) else None
            if v is not None and v not in allowed:
                raise HTTPException(400, f"{sec}.{key} must be one of: {', '.join(allowed)}")
        if isinstance(cc := body.get("claude_code"), dict) and "setting_sources" in cc:
            from .claude_code import valid_setting_sources

            if not valid_setting_sources(cc["setting_sources"]):
                raise HTTPException(400, "claude_code.setting_sources: empty, or a comma-separated list of user, project, local")
        if "orchestrator" in body and body["orchestrator"].get("effort") in ("xhigh", "max"):
            raise HTTPException(400, "The default orchestrator effort can be high at most; raise it per session instead.")
        get_config.cache_clear()
        _apply(S, save_config_patch(body), reset_providers=not set(body) <= NO_PROVIDER_RESET)
        if "claude_code" in body and (cc_ext := S.extensions.get("claude_code")) is not None:
            cc_ext.settings_changed()  # type: ignore[attr-defined]  # a new CLI path is probed again
        S.bus.publish("settings.updated", {"sections": list(body)})
        return await settings()

    @api.post("/settings/keys")
    async def put_key(body: dict = Body(...)) -> dict:
        provider, profile, key = body.get("provider"), (body.get("profile") or "default").strip(), (body.get("key") or "").strip()
        if provider not in PROVIDERS:
            raise HTTPException(400, "Unknown provider")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", profile):
            raise HTTPException(400, "Profile names: letters, digits, - and _")
        if len(key) < 10:
            raise HTTPException(400, "That doesn't look like an API key")
        try:
            set_key(provider, profile, key)
        except Exception as e:  # no keychain backend (e.g. Linux without a secret service)
            raise HTTPException(500, f"Couldn't save to the Keychain: {type(e).__name__}. "
                                     f"In development you can set {_env_name(provider, profile)} instead.") from e
        if profile not in S.config.profiles(provider):
            get_config.cache_clear()
            _apply(S, save_config_patch({"accounts": {provider: [*S.config.profiles(provider), profile]}}))
            S.bus.publish("settings.updated", {"sections": ["accounts"]})
        await _keys_changed(S, provider)
        return {"ok": True, "hint": key_hint(key)}

    @api.delete("/settings/keys/{provider}/{profile}")
    async def remove_key(provider: str, profile: str) -> dict:
        if provider not in PROVIDERS:
            raise HTTPException(400)
        delete_key(provider, profile)
        await _keys_changed(S, provider)
        return {"ok": True}

    @api.post("/settings/accounts/{provider}")
    async def set_profiles(provider: str, body: dict = Body(...)) -> dict:
        """Add or reorder profiles (the first is the default). Never removes one: existing profiles
        missing from the list (e.g. a stale page) keep their place after the listed ones, and their
        keys. Removing a profile is DELETE /settings/accounts/{provider}/{profile}."""
        raw = body.get("profiles")
        if provider not in PROVIDERS or not isinstance(raw, list) or not raw:
            raise HTTPException(400, "Send a non-empty list of profiles")
        bad = [p for p in raw if not isinstance(p, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", p)]
        if bad:
            raise HTTPException(400, "Profile names: letters, digits, - and _ (up to 32)")
        profiles = list(dict.fromkeys([*raw, *S.config.profiles(provider)]))
        get_config.cache_clear()
        _apply(S, save_config_patch({"accounts": {provider: profiles}}))
        S.bus.publish("settings.updated", {"sections": ["accounts"]})
        await _keys_changed(S, provider)
        return await settings()

    @api.delete("/settings/accounts/{provider}/{profile}")
    async def delete_profile(provider: str, profile: str) -> dict:
        """Remove a profile and its Keychain key. A provider keeps at least one profile."""
        current = S.config.profiles(provider)
        if provider not in PROVIDERS or profile not in current:
            raise HTTPException(404, "No such profile")
        if len(current) == 1:
            raise HTTPException(400, "A provider needs at least one profile; remove its key instead.")
        get_config.cache_clear()
        _apply(S, save_config_patch({"accounts": {provider: [p for p in current if p != profile]}}))
        _forget_profiles(S, provider, [profile])
        S.bus.publish("settings.updated", {"sections": ["accounts"]})
        await _keys_changed(S, provider)
        return await settings()

    # -------------------------------------------------------------- appearance

    @api.post("/settings/background")
    async def upload_background(file: UploadFile, theme: str = "dark") -> dict:
        if theme not in ("light", "dark"):
            raise HTTPException(400)
        ext = Path(file.filename or "").suffix.lower()
        if ext not in BG_EXT:
            raise HTTPException(400, "Use PNG, JPG, WebP, GIF, MP4/MOV (H.264 or HEVC) or WebM")
        d = data_dir() / "appearance"
        d.mkdir(exist_ok=True)
        for old in d.glob(f"bg-{theme}.*"):
            old.unlink()
        dest = d / f"bg-{theme}{ext}"
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        kind = "video" if ext in (".mp4", ".m4v", ".mov", ".webm") else "gif" if ext == ".gif" else "image"
        cur: dict[str, Any] = dict(S.config.appearance.get(theme) or {})
        cur.update({"path": str(dest), "kind": kind, "fit": cur.get("fit", "cover"), "dim": cur.get("dim", 0.35),
                    "blur": cur.get("blur", 0)})
        get_config.cache_clear()
        _apply(S, save_config_patch({"appearance": {theme: cur}}), reset_providers=False)
        S.bus.publish("settings.updated", {"sections": ["appearance"]})
        return S.config.appearance

    @api.delete("/settings/background/{theme}")
    async def clear_background(theme: str) -> dict:
        for old in (data_dir() / "appearance").glob(f"bg-{theme}.*"):
            old.unlink()
        cur = dict(S.config.appearance)
        cur[theme] = {}
        get_config.cache_clear()
        _apply(S, save_config_patch({"appearance": {theme: {"path": "", "kind": ""}}}), reset_providers=False)
        S.bus.publish("settings.updated", {"sections": ["appearance"]})
        return S.config.appearance
