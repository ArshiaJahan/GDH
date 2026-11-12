"""ElevenLabs client (official async SDK).

Checked against elevenlabs.io docs and SDK 2.76 on 2026-11-05:
- TTS models: eleven_v4 (flagship), eleven_v4_turbo, eleven_flash_v2_5, eleven_v3, eleven_multilingual_v2
- STT: scribe_v2 (scribe_v1 deprecated) · SFX: eleven_text_to_sound_v3 · Music: music_v2_5 (paid plans)
- Voice changer: eleven_multilingual_sts_v2, voice_settings as a JSON string
- Cost header: `character-cost`; quota: user.subscription (character_count / character_limit)
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..config import get_key
from .base import AuthStatus

SFX_MODEL = "eleven_text_to_sound_v3"
MUSIC_MODEL = "music_v2_5"
STS_MODEL = "eleven_multilingual_sts_v2"
SFX_CREDITS_PER_SECOND = 40
STS_CREDITS_PER_MINUTE = 1000
# Speech to text bills by audio duration, not characters. elevenlabs.io/pricing (checked
# 2026-11-06): "Speech to Text 330 credits per minute" on subscription plans; the API price
# list gives $0.22/hour for Scribe v2. The batch STT response carries no cost field, so the
# `character-cost` header is used when present, else duration × this rate.
STT_CREDITS_PER_MINUTE = 330


class ElevenLabsError(RuntimeError):
    def __init__(self, msg: str, status: int | None = None, code: str | None = None):
        super().__init__(msg)
        self.status = status
        self.code = code  # "no_key" when no key is saved for the profile


def ext_for(output_format: str) -> str:
    f = output_format.split("_")[0]
    return {"mp3": ".mp3", "wav": ".wav", "pcm": ".pcm", "opus": ".opus", "ulaw": ".ulaw", "alaw": ".alaw"}.get(f, ".mp3")


def _err(e: Exception) -> ElevenLabsError:
    if isinstance(e, ElevenLabsError):  # ours (e.g. no key, raised by `sdk`): keep its status and code
        return e
    status = getattr(e, "status_code", None)
    body = getattr(e, "body", None)
    detail = body
    if isinstance(body, dict):
        d = body.get("detail", body)
        detail = d.get("message") if isinstance(d, dict) else d
        if isinstance(d, dict) and d.get("status") == "quota_exceeded":
            return ElevenLabsError("ElevenLabs quota exceeded for this billing period.", status)
    return ElevenLabsError(f"ElevenLabs error {status}: {detail or e}"[:500], status)


def music_seed(seed: Any) -> int | None:
    """A music seed as an int (None stays None); anything that isn't a whole number >= 0 raises ElevenLabsError."""
    if seed is None or seed == "":
        return None
    if isinstance(seed, bool):
        raise ElevenLabsError(f"seed must be a whole number >= 0, not {seed!r}.", 422)
    try:
        if isinstance(seed, float):
            if not seed.is_integer():
                raise ValueError
            v = int(seed)
        else:
            v = int(str(seed).strip()) if isinstance(seed, str) else int(seed)
    except (TypeError, ValueError, OverflowError):
        raise ElevenLabsError(f"seed must be a whole number >= 0, not {seed!r}.", 422) from None
    if v < 0:
        raise ElevenLabsError(f"seed must be a whole number >= 0, not {seed!r}.", 422)
    return v


class ElevenLabsClient:
    def __init__(self, profile: str = "default", sdk: Any = None):
        self.profile = profile
        self._sdk = sdk
        self.models_cache: list[dict] = []

    @property
    def sdk(self):
        if self._sdk is None:
            key = get_key("elevenlabs", self.profile)
            if not key:
                raise ElevenLabsError(f"No ElevenLabs key for profile '{self.profile}'", 401, code="no_key")
            from elevenlabs.client import AsyncElevenLabs

            self._sdk = AsyncElevenLabs(api_key=key)
        return self._sdk

    def has_key(self) -> bool:
        return self._sdk is not None or bool(get_key("elevenlabs", self.profile))

    # ------------------------------------------------------------------ account

    async def subscription(self) -> dict:
        try:
            sub = await self.sdk.user.subscription.get()
        except ElevenLabsError:
            raise
        except Exception as e:  # noqa: BLE001
            raise _err(e) from e
        return sub.model_dump(mode="json") if hasattr(sub, "model_dump") else dict(sub)

    async def models(self) -> list[dict]:
        try:
            ms = await self.sdk.models.list()
        except Exception as e:  # noqa: BLE001
            raise _err(e) from e
        self.models_cache = [m.model_dump(mode="json") for m in ms]
        return self.models_cache

    @staticmethod
    def features_for(sub: dict) -> dict[str, bool]:
        paid = (sub.get("tier") or "free") != "free"
        return {"tts": True, "stt": True, "sfx": True, "voice_changer": True, "music": paid,
                "voice_library": paid, "voice_design": True,
                "instant_cloning": bool(sub.get("can_use_instant_voice_cloning")),
                "professional_cloning": bool(sub.get("can_use_professional_voice_cloning"))}

    async def check_auth(self) -> AuthStatus:
        st = AuthStatus(provider="elevenlabs", profile=self.profile, status="online", checked_at=time.time())
        if not self.has_key():
            st.status, st.error = "no_key", "No key in Keychain or environment"
            return st
        try:
            sub = await self.subscription()
            st.extra = {"subscription": sub, "features": self.features_for(sub)}
            try:
                st.models = [m["model_id"] for m in await self.models()]
            except ElevenLabsError:
                pass
        except ElevenLabsError as e:
            st.status = "auth_failed" if e.status in (401, 403) else "unreachable"
            st.error = str(e)
        except Exception as e:  # noqa: BLE001  (network)
            st.status, st.error = "unreachable", str(e)[:300]
        return st

    def credit_multiplier(self, model_id: str) -> float:
        for m in self.models_cache:
            if m.get("model_id") == model_id:
                return float((m.get("model_rates") or {}).get("character_cost_multiplier") or 1.0)
        return 0.5 if any(x in model_id for x in ("flash", "turbo", "conversational")) else 1.0

    # --------------------------------------------------------------- generation

    async def _audio(self, raw_call, **kw) -> tuple[bytes, dict]:
        try:
            async with raw_call(**kw) as r:
                data = b"".join([c async for c in r.data])
                return data, dict(r.headers)
        except ElevenLabsError:
            raise
        except Exception as e:  # noqa: BLE001
            raise _err(e) from e

    async def tts(self, text: str, voice_id: str, model_id: str, output_format: str,
                  voice_settings: dict | None = None, language_code: str | None = None) -> tuple[bytes, dict]:
        kw: dict[str, Any] = {"voice_id": voice_id, "text": text, "model_id": model_id, "output_format": output_format}
        if voice_settings:
            from elevenlabs import VoiceSettings

            kw["voice_settings"] = VoiceSettings(**{k: v for k, v in voice_settings.items() if v is not None})
        if language_code:
            kw["language_code"] = language_code
        return await self._audio(self.sdk.text_to_speech.with_raw_response.convert, **kw)

    async def sound_effect(self, text: str, duration_s: float | None, prompt_influence: float | None,
                           loop: bool = False, output_format: str = "mp3_44100_128") -> tuple[bytes, dict]:
        kw: dict[str, Any] = {"text": text, "model_id": SFX_MODEL, "output_format": output_format, "loop": loop}
        if duration_s:
            kw["duration_seconds"] = max(0.5, min(30.0, float(duration_s)))
        if prompt_influence is not None:
            kw["prompt_influence"] = prompt_influence
        return await self._audio(self.sdk.text_to_sound_effects.with_raw_response.convert, **kw)

    async def music(self, prompt: str, length_ms: int, instrumental: bool = False,
                    output_format: str = "mp3_44100_128", composition_plan: dict | None = None,
                    seed: int | None = None) -> tuple[bytes, dict]:
        """A prompt and a length, or a composition plan ({"chunks": [{text, duration_ms, positive_styles,
        negative_styles}]}) whose section durations music_v2/v2_5 always keep (trailer beat sheets)."""
        kw: dict[str, Any]
        if composition_plan:
            kw = {"composition_plan": composition_plan, "model_id": MUSIC_MODEL, "output_format": output_format}
            s = music_seed(seed)  # ElevenLabsError (not ValueError) on a bad seed
            if s is not None:
                kw["seed"] = s
        else:
            kw = {"prompt": prompt, "music_length_ms": max(3000, min(600_000, int(length_ms))), "model_id": MUSIC_MODEL,
                  "force_instrumental": instrumental, "output_format": output_format}
        return await self._audio(self.sdk.music.with_raw_response.compose, **kw)

    async def voice_changer(self, audio_path: Path, voice_id: str, output_format: str = "mp3_44100_128",
                            remove_background_noise: bool = False) -> tuple[bytes, dict]:
        with open(audio_path, "rb") as f:
            return await self._audio(self.sdk.speech_to_speech.with_raw_response.convert, voice_id=voice_id,
                                     audio=(audio_path.name, f.read()), model_id=STS_MODEL,
                                     output_format=output_format, remove_background_noise=remove_background_noise)

    async def transcribe(self, audio_path: Path, model_id: str = "scribe_v2", language_code: str | None = None,
                         diarize: bool = True, num_speakers: int | None = None) -> tuple[dict, dict]:
        """The transcript and the response headers (for `character-cost`, when sent)."""
        kw: dict[str, Any] = {"model_id": model_id, "diarize": diarize, "timestamps_granularity": "word",
                              "tag_audio_events": True}
        if language_code:
            kw["language_code"] = language_code
        if num_speakers:
            kw["num_speakers"] = num_speakers
        try:
            with open(audio_path, "rb") as f:
                raw = await self.sdk.speech_to_text.with_raw_response.convert(file=(audio_path.name, f.read()), **kw)
        except Exception as e:  # noqa: BLE001
            raise _err(e) from e
        r = raw.data
        return (r.model_dump(mode="json") if hasattr(r, "model_dump") else dict(r)), dict(raw.headers)

    # -------------------------------------------------------------------- voices

    async def voices(self, search: str | None = None, voice_type: str | None = None, page_size: int = 100) -> list[dict]:
        kw: dict[str, Any] = {"page_size": page_size}
        if search:
            kw["search"] = search
        if voice_type:
            kw["voice_type"] = voice_type
        try:
            r = await self.sdk.voices.search(**kw)
        except Exception as e:  # noqa: BLE001
            raise _err(e) from e
        return [_voice(v) for v in r.voices]

    async def shared_voices(self, search: str | None = None, page_size: int = 30) -> list[dict]:
        try:
            r = await self.sdk.voices.get_shared(page_size=page_size, search=search)
        except Exception as e:  # noqa: BLE001
            raise _err(e) from e
        out = []
        for v in r.voices:
            d = v.model_dump(mode="json")
            out.append({"voice_id": d.get("voice_id"), "name": d.get("name"), "category": d.get("category"),
                        "preview_url": d.get("preview_url"), "labels": {k: d.get(k) for k in ("gender", "age", "accent", "use_case") if d.get(k)},
                        "description": d.get("description"), "public_owner_id": d.get("public_owner_id"), "shared": True})
        return out

    async def add_shared_voice(self, public_user_id: str, voice_id: str, name: str) -> dict:
        try:
            r = await self.sdk.voices.share(public_user_id=public_user_id, voice_id=voice_id, new_name=name)
        except Exception as e:  # noqa: BLE001
            raise _err(e) from e
        return r.model_dump(mode="json") if hasattr(r, "model_dump") else {"ok": True}

    async def history(self, page_size: int = 100) -> list[dict]:
        try:
            r = await self.sdk.history.list(page_size=page_size)
        except Exception as e:  # noqa: BLE001
            raise _err(e) from e
        out = []
        for h in r.history:
            d = h.model_dump(mode="json")
            used = (d.get("character_count_change_to") or 0) - (d.get("character_count_change_from") or 0)
            out.append({"id": d.get("history_item_id"), "date_unix": d.get("date_unix"), "voice": d.get("voice_name"),
                        "model_id": d.get("model_id"), "text": d.get("text"), "credits": used, "source": d.get("source")})
        return out


def _voice(v: Any) -> dict:
    d = v.model_dump(mode="json") if hasattr(v, "model_dump") else dict(v)
    return {"voice_id": d.get("voice_id"), "name": d.get("name"), "category": d.get("category"),
            "labels": d.get("labels") or {}, "description": d.get("description"), "preview_url": d.get("preview_url"),
            "is_owner": d.get("is_owner")}


def char_cost(headers: dict, fallback: float) -> float:
    for k in ("character-cost", "x-character-count"):
        v = headers.get(k) or headers.get(k.title())
        if v is not None:
            try:
                return float(v)
            except ValueError:
                pass
    return fallback


def dumps(o: Any) -> str:
    return json.dumps(o, default=str)
