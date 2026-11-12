"""ElevenLabs: agent tools (tts, transcribe, sound_effect, music, list_voices), the
ElevenLabs page API, quota, and indexing every output under ElevenLabs.

Agent-triggered generations above `confirm_over_characters` ask first: speech compares its
character count, the other features their estimated credits.
"""
from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Body, FastAPI, HTTPException

from ..agent.tools import ToolContext, ToolDenied, ToolOutput, obj
from ..config import media_dir
from ..core.types import Usage, new_id
from ..usage import BudgetExceeded
from ..providers.elevenlabs_client import (SFX_CREDITS_PER_SECOND, STS_CREDITS_PER_MINUTE, STT_CREDITS_PER_MINUTE,
                                           ElevenLabsClient, ElevenLabsError, char_cost, ext_for, music_seed)

if TYPE_CHECKING:
    from ..app import AppState

log = logging.getLogger(__name__)
QUOTA_REFRESH_DELAY_S = 3.0  # coalesces a burst of generations into one subscription read
MUSIC_CREDITS_PER_MINUTE = 1500  # rough estimate for the confirm card; music bills per minute
PLAN_MAX_LINES = 30        # ElevenLabs limits on a composition plan chunk's text
PLAN_MAX_LINE_CHARS = 200


def composition_plan_checked(plan: Any) -> dict:
    """A music composition plan ({"chunks": [{text, duration_ms 3000-120000, positive_styles,
    negative_styles?}]}, music_v2/v2_5 keep each section's length exactly), normalized; raises
    ElevenLabsError with every problem found. Chunk text: at most 30 lines of at most 200 characters
    (ElevenLabs' limits)."""
    errs: list[str] = []
    if isinstance(plan, str):  # some models send the object as JSON text
        try:
            plan = json.loads(plan)
        except ValueError:
            raise ElevenLabsError("composition_plan is not valid JSON.") from None
    chunks = plan.get("chunks") if isinstance(plan, dict) else None
    if not isinstance(chunks, list) or not chunks:
        raise ElevenLabsError("composition_plan needs a non-empty chunks list.")
    out = []
    for i, ch in enumerate(chunks):
        if not isinstance(ch, dict):
            errs.append(f"chunk {i + 1} must be an object")
            continue
        text = str(ch.get("text") or "").strip()
        dur = ch.get("duration_ms")
        pos = ch.get("positive_styles") or []
        neg = ch.get("negative_styles") or []
        if not text:
            errs.append(f"chunk {i + 1} needs text (e.g. \"[Build] rising synths\")")
        else:
            lines = text.splitlines()
            if len(lines) > PLAN_MAX_LINES:
                errs.append(f"chunk {i + 1} text has {len(lines)} lines (ElevenLabs allows at most {PLAN_MAX_LINES})")
            long_ = [k + 1 for k, ln in enumerate(lines) if len(ln) > PLAN_MAX_LINE_CHARS]
            if long_:
                errs.append(f"chunk {i + 1} text line {long_[0]} is {len(lines[long_[0] - 1])} characters "
                            f"(ElevenLabs allows at most {PLAN_MAX_LINE_CHARS} per line)")
        if isinstance(dur, bool) or not isinstance(dur, (int, float)) or not 3000 <= dur <= 120_000:
            errs.append(f"chunk {i + 1} duration_ms must be 3000-120000")
        if not isinstance(pos, list) or not all(isinstance(s, str) for s in pos):
            errs.append(f"chunk {i + 1} positive_styles must be a list of strings")
        if not isinstance(neg, list) or not all(isinstance(s, str) for s in neg):
            errs.append(f"chunk {i + 1} negative_styles must be a list of strings")
        if not errs:
            c = {"text": text, "duration_ms": int(dur), "positive_styles": list(pos)}
            if neg:
                c["negative_styles"] = list(neg)
            out.append(c)
    if not errs and sum(c["duration_ms"] for c in out) > 600_000:
        errs.append("the chunks add up to more than 10 minutes")
    if errs:
        raise ElevenLabsError("Invalid composition_plan: " + "; ".join(errs))
    return {"chunks": out}


def stt_credits(headers: dict, audio_seconds: float) -> tuple[float, bool]:
    """Credits for a transcription and whether they are estimated. The API's
    `character-cost` header wins when present; otherwise audio minutes × 330 credits
    (ElevenLabs bills speech to text per minute of audio)."""
    est = round(max(0.0, audio_seconds) / 60 * STT_CREDITS_PER_MINUTE, 1)
    # Only `character-cost` is a credit count; `x-character-count` (which char_cost also accepts for
    # speech) counts characters, which says nothing about a transcription's cost.
    v = headers.get("character-cost") or headers.get("Character-Cost")
    if v is not None:
        try:
            return float(v), False
        except ValueError:
            pass
    return est, True


def _audio_seconds(path: Path) -> float | None:
    try:
        from mutagen import File as MFile  # optional

        f = MFile(str(path))
        return float(f.info.length) if f and f.info else None
    except Exception:
        return None


class ElevenLabsService:
    available = True

    def __init__(self, app: "AppState"):
        self.app = app
        self.clients: dict[str, ElevenLabsClient] = {}
        self._voice_names: dict[str, str] = {}
        self._quota_task: asyncio.Task | None = None
        self._quota_dirty = False
        self._quota_profiles: set[str | None] = set()

    def client_for(self, profile: str | None = None) -> ElevenLabsClient:
        profile = profile or self.app.config.profiles("elevenlabs")[0]
        if profile not in self.clients:
            self.clients[profile] = ElevenLabsClient(profile)
        return self.clients[profile]

    def profile_for(self, session_id: str | None, profile: str | None = None) -> str:
        """Which ElevenLabs profile to use: one the caller picked (the ElevenLabs page), else the
        session's choice, else the default (first) profile."""
        if profile and profile in self.app.config.profiles("elevenlabs"):
            return profile
        session = self.app.store.get(session_id) if session_id else None
        return self.app.config.profile_for(session, "elevenlabs")

    def client_for_session(self, session_id: str | None, profile: str | None = None) -> ElevenLabsClient:
        return self.client_for(self.profile_for(session_id, profile))

    @property
    def defaults(self) -> dict:
        return self.app.config.elevenlabs

    def features(self, profile: str | None = None) -> dict:
        profile = profile or self.app.config.profiles("elevenlabs")[0]
        r = self.app.db.one("SELECT extra, status, checked_at FROM auth_status WHERE provider='elevenlabs' AND profile=? "
                            "ORDER BY checked_at DESC", [profile])
        if not r:
            return {"status": "unknown", "features": {}}
        extra = json.loads(r["extra"])
        return {"status": r["status"], "features": extra.get("features", {}), "subscription": extra.get("subscription"),
                "subscription_checked_at": extra.get("subscription_checked_at") or r["checked_at"]}

    # ------------------------------------------------------------------ quota

    def refresh_quota_soon(self, profile: str | None = None) -> None:
        """Re-read the subscription (credits used / left) shortly after a generation, so My usage
        and the ElevenLabs page don't wait for the 15-minute auth check. Debounced: a burst of
        generations (variations, parallel TTS) costs one GET /v1/user/subscription."""
        self._quota_dirty = True
        self._quota_profiles.add(profile)
        if self._quota_task is not None and not self._quota_task.done():
            return
        try:
            self._quota_task = asyncio.get_running_loop().create_task(self._refresh_quota())
        except RuntimeError:  # no event loop (sync tests, scripts)
            pass

    async def _refresh_quota(self) -> None:
        while self._quota_dirty:
            await asyncio.sleep(QUOTA_REFRESH_DELAY_S)
            self._quota_dirty = False  # generations from here on schedule another pass
            profiles, self._quota_profiles = self._quota_profiles or {None}, set()
            for profile in profiles:
                try:
                    await self.refresh_quota(profile)
                except Exception:  # noqa: BLE001  (best effort; the auth check runs anyway)
                    log.debug("quota refresh failed", exc_info=True)

    async def refresh_quota(self, profile: str | None = None) -> dict | None:
        profile = profile or self.app.config.profiles("elevenlabs")[0]
        row = self.app.db.one("SELECT 1 FROM auth_status WHERE provider='elevenlabs' AND profile=?", [profile])
        if not row:
            return None  # never checked: leave it to the status checker
        sub = await self.client_for(profile).subscription()
        now = time.time()
        # Set just the two subscription keys in one statement, so a status check that rewrote the
        # row meanwhile (features, models) isn't overwritten with what we read before the await.
        # subscription_checked_at is what My usage sorts and labels the quota by.
        self.app.db.execute(
            "UPDATE auth_status SET extra=json_set(CASE WHEN json_valid(extra) THEN extra ELSE '{}' END, "
            "'$.subscription', json(?), '$.subscription_checked_at', ?) WHERE provider='elevenlabs' AND profile=?",
            [json.dumps(sub, default=str), now, profile])
        self.app.bus.publish("elevenlabs.quota", {"profile": profile, "subscription": sub, "checked_at": now})
        return sub

    async def default_voice(self, client: ElevenLabsClient) -> str:
        if v := self.defaults.get("voice_id"):
            return v
        voices = await client.voices(page_size=10)
        if not voices:
            raise ElevenLabsError("No voices in this ElevenLabs account; pick one on the ElevenLabs page.")
        return voices[0]["voice_id"]

    async def voice_name(self, client: ElevenLabsClient, voice_id: str) -> str:
        if voice_id not in self._voice_names:
            try:
                for v in await client.voices(page_size=100):
                    self._voice_names[v["voice_id"]] = v["name"]
            except ElevenLabsError:
                pass
        return self._voice_names.get(voice_id, voice_id)

    # ---------------------------------------------------------------- generate

    async def _confirm(self, session_id: str | None, source: str, feature: str, credits: float, preview: str,
                       characters: int) -> None:
        self.app.usage.check(session_id)  # spend limits pause ElevenLabs too
        limit = float(self.defaults.get("confirm_over_characters") or 0)
        # Speech is measured in characters (as the setting's name says); other features by estimated credits.
        amount = characters if feature == "tts" else credits
        if source != "agent" or not limit or amount <= limit:
            return
        if self.app.approvals.allowlisted("elevenlabs", feature):
            return
        res = await self.app.approvals.ask(session_id, "elevenlabs", {
            "subject": f"{feature}: {characters} characters", "feature": feature, "characters": characters,
            "est_credits": round(credits), "preview": preview[:400]})
        if res["status"] != "approved":
            raise ToolDenied(f"User declined the {feature} generation.")

    async def _save(self, *, data: bytes, ext: str, feature: str, model: str, session_id: str | None, source: str,
                    title: str, text: str, credits: float, characters: int, voice: str | None, meta: dict,
                    message_id: str | None = None, job: str | None = None, profile: str = "default") -> dict:
        d = media_dir() / "elevenlabs"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{time.strftime('%Y%m%d-%H%M%S')}-{feature}-{new_id()[:6]}{ext}"
        path.write_bytes(data)
        iid = self.app.items.add(kind="media", subtype="audio", source="tool" if source == "agent" else source,
                                 session_id=session_id, message_id=message_id, provider="elevenlabs", model=model,
                                 title=title, path=str(path), mime=mimetypes.guess_type(path.name)[0] or "audio/mpeg",
                                 extracted_text=text,
                                 meta={"feature": feature, "credits": credits, "characters": characters,
                                       "voice": voice, **meta})
        self.app.usage.record(provider="elevenlabs", model=model, feature=feature, voice=voice, session_id=session_id,
                              role="tool" if source == "agent" else "main", profile=profile,
                              usage=Usage(characters=characters, credits=credits))
        self.refresh_quota_soon(profile)
        out = {"item_id": iid, "path": str(path), "credits": credits, "characters": characters, "title": title,
               "feature": feature, "model": model}
        self.app.bus.publish("elevenlabs.generated", out, session_id)
        return out

    async def _run_job(self, session_id: str | None, title: str, coro):
        try:
            self.app.usage.check(session_id)
        except Exception as e:
            coro.close()
            raise ElevenLabsError(str(e), 402) from e
        jid = self.app.jobs.start(session_id, "elevenlabs", title)
        try:
            r = await coro
            self.app.jobs.finish(jid, "done", credits=r.get("credits") if isinstance(r, dict) else None)
            return r
        except asyncio.CancelledError:
            self.app.jobs.finish(jid, "cancelled")
            raise
        except Exception as e:
            self.app.jobs.log(jid, str(e))
            self.app.jobs.finish(jid, "failed")
            raise

    async def tts(self, text: str, *, session_id: str | None, source: str, voice_id: str | None = None,
                  model_id: str | None = None, output_format: str | None = None, voice_settings: dict | None = None,
                  language_code: str | None = None, message_id: str | None = None, profile: str | None = None) -> dict:
        c = self.client_for_session(session_id, profile)
        model = model_id or self.defaults.get("model_id", "eleven_v4")
        fmt = output_format or self.defaults.get("output_format", "mp3_44100_128")
        est = len(text) * c.credit_multiplier(model)
        await self._confirm(session_id, source, "tts", est, text, len(text))

        async def go():
            vid = voice_id or await self.default_voice(c)
            data, headers = await c.tts(text, vid, model, fmt, voice_settings, language_code)
            vname = await self.voice_name(c, vid)
            return await self._save(data=data, ext=ext_for(fmt), feature="tts", model=model, session_id=session_id,
                                    source=source, title=f"Speech: {text[:48]}", text=text,
                                    credits=char_cost(headers, est), characters=len(text), voice=vname,
                                    meta={"voice_id": vid, "output_format": fmt, "settings": voice_settings},
                                    message_id=message_id, profile=c.profile)

        return await self._run_job(session_id, f"Text to speech ({len(text)} chars)", go())

    async def sound_effect(self, text: str, *, session_id: str | None, source: str, duration_s: float | None = None,
                           prompt_influence: float | None = None, loop: bool = False,
                           message_id: str | None = None, profile: str | None = None) -> dict:
        c = self.client_for_session(session_id, profile)
        est = SFX_CREDITS_PER_SECOND * (duration_s or 5)
        await self._confirm(session_id, source, "sound_effect", est, text, len(text))

        async def go():
            data, headers = await c.sound_effect(text, duration_s, prompt_influence, loop)
            return await self._save(data=data, ext=".mp3", feature="sfx", model="eleven_text_to_sound_v3",
                                    session_id=session_id, source=source, title=f"Sound: {text[:48]}", text=text,
                                    credits=char_cost(headers, est), characters=len(text), voice=None,
                                    meta={"duration_s": duration_s, "loop": loop}, message_id=message_id,
                                    profile=c.profile)

        return await self._run_job(session_id, f"Sound effect: {text[:40]}", go())

    async def music(self, prompt: str, *, session_id: str | None, source: str, duration_s: float = 30,
                    instrumental: bool = False, message_id: str | None = None, profile: str | None = None,
                    composition_plan: dict | None = None, seed: int | None = None) -> dict:
        plan = composition_plan_checked(composition_plan) if composition_plan else None
        seed = music_seed(seed)  # a clean ElevenLabsError for a seed that isn't a whole number
        if plan and instrumental:
            # A composition plan has no force_instrumental switch: keep vocals out of every section instead.
            for ch in plan["chunks"]:
                neg = ch.setdefault("negative_styles", [])
                if not any(s.strip().lower() == "vocals" for s in neg):
                    neg.append("vocals")
        if plan:
            duration_s = sum(ch["duration_ms"] for ch in plan["chunks"]) / 1000
            text = "\n".join(ch["text"] for ch in plan["chunks"])
            prompt = prompt or plan["chunks"][0]["text"]
        elif not prompt:
            raise ElevenLabsError("Music needs a prompt or a composition_plan.")
        else:
            text = prompt
        c = self.client_for_session(session_id, profile)
        if not self.features(c.profile).get("features", {}).get("music", True):
            raise ElevenLabsError("Music needs a paid ElevenLabs plan.")
        est = duration_s / 60 * MUSIC_CREDITS_PER_MINUTE  # rough; the response header gives the real cost
        await self._confirm(session_id, source, "music", est, text, len(text))

        async def go():
            data, headers = await c.music(prompt, int(duration_s * 1000), instrumental, composition_plan=plan,
                                          seed=seed if plan else None)
            meta: dict[str, Any] = {"duration_s": duration_s, "instrumental": instrumental}
            if plan:
                # instrumental with a plan = "vocals" in every chunk's negative_styles (the plan below is what was sent)
                if instrumental:
                    meta["instrumental_via"] = "negative_styles"
                meta.update(composition_plan=plan, seed=seed,
                            sections=[{"text": ch["text"], "duration_ms": ch["duration_ms"]} for ch in plan["chunks"]])
            return await self._save(data=data, ext=".mp3", feature="music", model="music_v2_5", session_id=session_id,
                                    source=source, title=f"Music: {prompt[:48]}", text=text,
                                    credits=char_cost(headers, est), characters=len(text), voice=None,
                                    meta=meta, message_id=message_id, profile=c.profile)

        return await self._run_job(session_id, f"Music: {prompt[:40]}", go())

    async def voice_changer(self, audio: Path, voice_id: str, *, session_id: str | None, source: str,
                            profile: str | None = None) -> dict:
        c = self.client_for_session(session_id, profile)
        secs = _audio_seconds(audio) or 60
        est = secs / 60 * STS_CREDITS_PER_MINUTE

        async def go():
            data, headers = await c.voice_changer(audio, voice_id)
            vname = await self.voice_name(c, voice_id)
            return await self._save(data=data, ext=".mp3", feature="voice_changer", model="eleven_multilingual_sts_v2",
                                    session_id=session_id, source=source, title=f"Voice changed: {audio.name}",
                                    text="", credits=char_cost(headers, est), characters=0, voice=vname,
                                    meta={"voice_id": voice_id, "source_file": str(audio)}, profile=c.profile)

        return await self._run_job(session_id, f"Voice changer: {audio.name}", go())

    async def transcribe(self, audio: Path, *, session_id: str | None, source: str, language_code: str | None = None,
                         diarize: bool = True, num_speakers: int | None = None, source_item: str | None = None,
                         profile: str | None = None) -> dict:
        self._check_data_policy(source_item)
        c = self.client_for_session(session_id, profile)
        model = self.defaults.get("stt_model_id", "scribe_v2")

        async def go():
            r, headers = await c.transcribe(audio, model, language_code, diarize, num_speakers)
            words = [w for w in r.get("words", []) if w.get("type") != "spacing"]
            text = r.get("text", "")
            # Speaker-labelled transcript for the model and the viewer.
            lines, cur, buf = [], None, []
            for w in words:
                spk = w.get("speaker_id")
                if spk != cur and buf:
                    lines.append(f"{cur or 'speaker'}: {' '.join(buf)}")
                    buf = []
                cur = spk
                buf.append(w.get("text", ""))
            if buf:
                lines.append(f"{cur or 'speaker'}: {' '.join(buf)}")
            labelled = "\n".join(lines) if diarize and lines else text
            d = media_dir() / "elevenlabs"
            d.mkdir(parents=True, exist_ok=True)
            tpath = d / f"{time.strftime('%Y%m%d-%H%M%S')}-transcript-{new_id()[:6]}.json"
            tpath.write_text(json.dumps({"source": str(audio), "text": text, "labelled": labelled,
                                         "language_code": r.get("language_code"), "words": words}, indent=1))
            secs = r.get("audio_duration_secs") or (words[-1]["end"] if words else 0) or _audio_seconds(audio) or 0
            credits, estimated = stt_credits(headers, secs)
            iid = self.app.items.add(kind="file", subtype="transcript", source="tool" if source == "agent" else source,
                                     session_id=session_id, provider="elevenlabs", model=model,
                                     title=f"Transcript: {audio.name}", path=str(tpath), mime="application/json",
                                     extracted_text=labelled,
                                     meta={"audio": str(audio), "audio_item": source_item, "duration_s": secs,
                                           "language": r.get("language_code"), "feature": "stt",
                                           "credits": credits, "credits_estimated": estimated})
            self.app.usage.record(provider="elevenlabs", model=model, feature="stt", session_id=session_id,
                                  role="tool" if source == "agent" else "main", usage=Usage(credits=credits),
                                  profile=c.profile)
            self.refresh_quota_soon(c.profile)
            out = {"item_id": iid, "path": str(tpath), "text": text, "labelled": labelled,
                   "language": r.get("language_code"), "duration_s": secs, "words": words, "credits": credits,
                   "credits_estimated": estimated}
            self.app.bus.publish("elevenlabs.generated", {**{k: out[k] for k in ("item_id", "path", "language")},
                                                          "feature": "stt", "title": f"Transcript: {audio.name}"},
                                 session_id)
            return out

        return await self._run_job(session_id, f"Transcribe {audio.name}", go())

    def _check_data_policy(self, item_id: str | None) -> None:
        if not item_id:
            return
        it = self.app.items.get(item_id)
        if it and it["meta"].get("sensitive") and "elevenlabs" not in self.app.config.data_policy.get(
                "sensitive_allowed", []):
            raise ToolDenied("That file is marked sensitive and your data policy doesn't allow sending it to "
                             "ElevenLabs. Change it in Settings → Data policy.")

    def resolve_audio(self, ctx_or_session: Any, ref: str) -> tuple[Path, str | None]:
        """An item id or a path → local file."""
        if ref.startswith("itm_"):
            it = self.app.items.get(ref)
            if not it or not it.get("path"):
                raise ToolDenied(f"No item {ref}")
            return Path(it["path"]), ref
        if isinstance(ctx_or_session, ToolContext):
            return ctx_or_session.resolve_path(ref), None
        return Path(ref), None


def _register_tools(S: "AppState", svc: ElevenLabsService) -> None:
    reg = S.tools

    def summary(r: dict) -> ToolOutput:
        return ToolOutput(f"Saved {r['title']} as item {r['item_id']} ({r['path']}), "
                          f"{r['credits']:.0f} credits.", items=[r["item_id"]])

    @reg.add("tts", "ElevenLabs text to speech. Returns an audio item id. Long texts: one call per paragraph or "
             "scene, in parallel.",
             obj({"text": {"type": "string"}, "voice_id": {"type": "string"}, "model_id": {"type": "string"},
                  "output_format": {"type": "string"}, "language_code": {"type": "string"},
                  "stability": {"type": "number"}, "similarity_boost": {"type": "number"},
                  "style": {"type": "number"}, "speed": {"type": "number"}}, ["text"]))
    async def tts(ctx: ToolContext, a: dict) -> ToolOutput:
        vs = {k: a[k] for k in ("stability", "similarity_boost", "style", "speed") if a.get(k) is not None}
        try:
            r = await svc.tts(a["text"], session_id=ctx.session_id, source="agent", voice_id=a.get("voice_id"),
                              model_id=a.get("model_id"), output_format=a.get("output_format"),
                              voice_settings=vs or None, language_code=a.get("language_code"),
                              message_id=ctx.message_id)
        except (ElevenLabsError, BudgetExceeded) as e:
            return ToolOutput(str(e), is_error=True)
        return summary(r)

    @reg.add("transcribe", "ElevenLabs speech to text (Scribe) for an audio/video item id or a path in the session "
             "folder. Returns a transcript item id and the speaker-labelled text.",
             obj({"source": {"type": "string", "description": "item id (itm_…) or path"},
                  "language_code": {"type": "string"}, "diarize": {"type": "boolean"},
                  "num_speakers": {"type": "integer"}}, ["source"]))
    async def transcribe(ctx: ToolContext, a: dict) -> ToolOutput:
        path, item = svc.resolve_audio(ctx, a["source"])
        try:
            r = await svc.transcribe(path, session_id=ctx.session_id, source="agent",
                                     language_code=a.get("language_code"), diarize=a.get("diarize", True),
                                     num_speakers=a.get("num_speakers"), source_item=item)
        except ElevenLabsError as e:
            return ToolOutput(str(e), is_error=True)
        text = r["labelled"]
        if len(text) > 20000:
            text = text[:20000] + f"\n…[truncated; full transcript in item {r['item_id']}]"
        return ToolOutput(f"Transcript item {r['item_id']} ({r['language']}, {r['duration_s']:.0f}s):\n{text}",
                          items=[r["item_id"]])

    @reg.add("sound_effect", "ElevenLabs sound effect from a description (0.5–30 s).",
             obj({"description": {"type": "string"}, "duration_s": {"type": "number"},
                  "prompt_influence": {"type": "number"}, "loop": {"type": "boolean"}}, ["description"]))
    async def sfx(ctx: ToolContext, a: dict) -> ToolOutput:
        try:
            r = await svc.sound_effect(a["description"], session_id=ctx.session_id, source="agent",
                                       duration_s=a.get("duration_s"), prompt_influence=a.get("prompt_influence"),
                                       loop=bool(a.get("loop")), message_id=ctx.message_id)
        except (ElevenLabsError, BudgetExceeded) as e:
            return ToolOutput(str(e), is_error=True)
        return summary(r)

    @reg.add("music", "ElevenLabs music (paid plans): a prompt with duration_s 3–600, or a composition_plan "
             "whose sections keep their exact lengths (e.g. a trailer's beat sheet). Composition plan: "
             "{\"chunks\": [{\"text\": \"[Build] ...\", \"duration_ms\": 3000-120000, \"positive_styles\": [...], "
             "\"negative_styles\": [...]}]}, chunk text at most 30 lines of 200 characters; seed (a whole number) "
             "works only with a plan; instrumental with a plan adds \"vocals\" to every chunk's negative_styles.",
             obj({"prompt": {"type": "string"}, "duration_s": {"type": "number"},
                  "instrumental": {"type": "boolean"},
                  "composition_plan": {"type": "object", "description": "{chunks: [{text, duration_ms, "
                                                                        "positive_styles, negative_styles}]}"},
                  "seed": {"type": "integer"}}))
    async def music(ctx: ToolContext, a: dict) -> ToolOutput:
        try:
            r = await svc.music(str(a.get("prompt") or ""), session_id=ctx.session_id, source="agent",
                                duration_s=float(a.get("duration_s") or 30), instrumental=bool(a.get("instrumental")),
                                message_id=ctx.message_id, composition_plan=a.get("composition_plan"),
                                seed=a.get("seed"))
        except (ElevenLabsError, BudgetExceeded) as e:
            return ToolOutput(str(e), is_error=True)
        return summary(r)

    @reg.add("list_voices", "List ElevenLabs voices in the account (id, name, labels).",
             obj({"search": {"type": "string"}}), read_only=True)
    async def list_voices(ctx: ToolContext, a: dict) -> ToolOutput:
        try:
            vs = await svc.client_for_session(ctx.session_id).voices(search=a.get("search"))
        except ElevenLabsError as e:
            return ToolOutput(str(e), is_error=True)
        lines = [f"{v['voice_id']}  {v['name']}  {', '.join(f'{k}={x}' for k, x in (v['labels'] or {}).items())}"
                 for v in vs]
        return ToolOutput("\n".join(lines) or "No voices.")


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    svc = ElevenLabsService(S)
    S.extensions["elevenlabs"] = svc
    _register_tools(S, svc)

    def wrap(e: Exception) -> HTTPException:
        if isinstance(e, BudgetExceeded):  # a spend limit: a clean 402 the page shows as a toast, not a 500
            return HTTPException(402, str(e), headers={"X-GDW-Error": "budget"})
        if getattr(e, "code", None) == "no_key":  # nothing saved for the profile: a client-side state, not a gateway error
            return HTTPException(400, str(e), headers={"X-GDW-Error": "no_key"})
        status = getattr(e, "status", None) or 502
        return HTTPException(400 if status == 422 else (402 if "quota" in str(e) else status if status < 500 else 502),
                             str(e))

    # The page passes `profile` (its picker) and/or `session_id`; see ElevenLabsService.profile_for.
    @api.get("/elevenlabs/status")
    async def status(profile: str | None = None, session_id: str | None = None) -> dict:
        c = svc.client_for_session(session_id, profile)
        f = svc.features(c.profile)
        return {**f, "defaults": svc.defaults, "has_key": c.has_key(), "profile": c.profile,
                "profiles": S.config.profiles("elevenlabs"),
                "models": [m for m in c.models_cache if m.get("can_do_text_to_speech")]}

    @api.get("/elevenlabs/models")
    async def models(profile: str | None = None, session_id: str | None = None) -> list[dict]:
        try:
            return await svc.client_for_session(session_id, profile).models()
        except ElevenLabsError as e:
            raise wrap(e) from e

    @api.get("/elevenlabs/voices")
    async def voices(search: str | None = None, shared: bool = False, profile: str | None = None,
                     session_id: str | None = None) -> list[dict]:
        try:
            c = svc.client_for_session(session_id, profile)
            return await (c.shared_voices(search) if shared else c.voices(search=search))
        except ElevenLabsError as e:
            raise wrap(e) from e

    @api.post("/elevenlabs/voices/add")
    async def add_voice(body: dict = Body(...)) -> dict:
        try:
            c = svc.client_for_session(body.get("session_id"), body.get("profile"))
            return await c.add_shared_voice(body["public_owner_id"], body["voice_id"], body["name"])
        except ElevenLabsError as e:
            raise wrap(e) from e

    @api.get("/elevenlabs/favorites")
    async def favs() -> list[str]:
        return S.db.kv_get("el_favorites", [])

    @api.post("/elevenlabs/favorites")
    async def set_favs(body: dict = Body(...)) -> list[str]:
        S.db.kv_set("el_favorites", list(dict.fromkeys(body.get("voice_ids", []))))
        return S.db.kv_get("el_favorites", [])

    @api.post("/elevenlabs/tts")
    async def ui_tts(body: dict = Body(...)) -> dict:
        try:
            return await svc.tts(body["text"], session_id=body.get("session_id"), source="user",
                                 voice_id=body.get("voice_id"), model_id=body.get("model_id"),
                                 output_format=body.get("output_format"), voice_settings=body.get("voice_settings"),
                                 language_code=body.get("language_code"), profile=body.get("profile"))
        except (ElevenLabsError, BudgetExceeded) as e:
            raise wrap(e) from e

    @api.post("/elevenlabs/stt")
    async def ui_stt(body: dict = Body(...)) -> dict:
        try:
            path = Path(body["path"]) if body.get("path") else Path(S.items.get(body["item_id"])["path"])
            return await svc.transcribe(path, session_id=body.get("session_id"), source="user",
                                        language_code=body.get("language_code") or None,
                                        diarize=body.get("diarize", True), num_speakers=body.get("num_speakers"),
                                        source_item=body.get("item_id"), profile=body.get("profile"))
        except (ElevenLabsError, ToolDenied, BudgetExceeded) as e:
            raise wrap(e) from e

    @api.post("/elevenlabs/sfx")
    async def ui_sfx(body: dict = Body(...)) -> list[dict]:
        n = max(1, min(int(body.get("variations") or 1), 4))
        try:
            return list(await asyncio.gather(*(svc.sound_effect(
                body["text"], session_id=body.get("session_id"), source="user", duration_s=body.get("duration_s"),
                prompt_influence=body.get("prompt_influence"), loop=bool(body.get("loop")),
                profile=body.get("profile")) for _ in range(n))))
        except (ElevenLabsError, BudgetExceeded) as e:
            raise wrap(e) from e

    @api.post("/elevenlabs/music")
    async def ui_music(body: dict = Body(...)) -> list[dict]:
        n = max(1, min(int(body.get("variations") or 1), 3))
        try:
            seed = music_seed(body.get("seed"))
            # each variation gets its own seed (seed, seed+1, ...) so they differ yet stay reproducible
            return list(await asyncio.gather(*(svc.music(
                str(body.get("prompt") or ""), session_id=body.get("session_id"), source="user",
                duration_s=float(body.get("duration_s") or 30), instrumental=bool(body.get("instrumental")),
                profile=body.get("profile"), composition_plan=body.get("composition_plan"),
                seed=None if seed is None else seed + i) for i in range(n))))
        except (ElevenLabsError, BudgetExceeded) as e:
            raise wrap(e) from e

    @api.post("/elevenlabs/voice-changer")
    async def ui_sts(body: dict = Body(...)) -> dict:
        try:
            return await svc.voice_changer(Path(body["path"]), body["voice_id"], session_id=body.get("session_id"),
                                           source="user", profile=body.get("profile"))
        except (ElevenLabsError, BudgetExceeded) as e:
            raise wrap(e) from e

    @api.get("/elevenlabs/history")
    async def history() -> list[dict]:
        return S.items.list(provider="elevenlabs", limit=500)

    @api.get("/elevenlabs/transcript")
    async def transcript(item_id: str) -> dict:
        it = S.items.get(item_id)
        if not it:
            raise HTTPException(404)
        return json.loads(Path(it["path"]).read_text())
