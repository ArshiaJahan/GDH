"""Context-window management: estimate how full a request is, summarize older turns (Compact,
by hand or automatically before the window fills) and, as a last resort, stub old tool output
in the outgoing request so a long autonomous turn can't overflow the model's window."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Callable

from ..core.types import (AudioBlock, ChatRequest, FileBlock, ImageBlock, Message, TextBlock, ThinkingBlock,
                          ToolResultBlock, ToolUseBlock)

if TYPE_CHECKING:
    from ..app import AppState

CHARS_PER_TOKEN = 3.6
IMAGE_TOKENS = 1600
AUTO_COMPACT_AT = 0.8  # share of the window at which the main loop compacts before its next call
TARGET_AFTER = 0.5  # the mildest cut that brings the kept part under this share is used
WARN_AT, DANGER_AT = 0.7, 0.9  # Context card warnings
KEEP_RECENT_TURNS = 3  # Compact keeps the last 3 user turns when it can...
KEEP_TOOL_EXCHANGES = 4  # ...else (one long autonomous turn) the last 4 tool exchanges
TRANSCRIPT_MAX = 400_000  # chars sent to the summarizer: head (goal) + tail, middle elided
TRANSCRIPT_HEAD = 80_000
GOAL_MAX = 4000
GOAL_HEAD = "\n\n**The user's current request (verbatim):**\n\n"

COMPACT_PROMPT = """Summarize the conversation below so an agent can continue the work without it.
Keep: the user's goals and constraints, decisions made and why, file paths, commands, item IDs,
open questions, and what was in progress. Drop chit-chat and tool output details.
Write tight Markdown bullets, at most 400 words. No preamble."""

STUB = "[Older tool output removed to fit the context window (about {n:,} tokens). Run the tool again if you need it.]"


class ContextFull(Exception):
    """The request can't be made to fit the model's window (shown to the user as is)."""


def est(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN)


def block_tokens(b) -> tuple[int, int]:
    """(message tokens, attachment tokens) estimate for one block."""
    if isinstance(b, TextBlock):
        return est(b.text), 0
    if isinstance(b, ThinkingBlock):
        return est(b.thinking), 0
    if isinstance(b, ToolUseBlock):
        return est(json.dumps(b.input)), 0
    if isinstance(b, ToolResultBlock):
        return sum(sum(block_tokens(c)) for c in b.content), 0
    if isinstance(b, ImageBlock):
        return 0, IMAGE_TOKENS
    if isinstance(b, FileBlock):
        return 0, est(b.text) if b.text else 3000
    if isinstance(b, AudioBlock):
        return 0, est(b.transcript or "") + 50
    return 0, 0


def msg_parts(m: Message) -> tuple[int, int]:
    msg = att = 0
    for b in m.content:
        a, t = block_tokens(b)
        msg, att = msg + a, att + t
    return msg, att


def messages_tokens(msgs: list[Message]) -> int:
    return sum(sum(msg_parts(m)) for m in msgs)


def is_user_turn(m: Message) -> bool:
    """A message the user typed (not tool results, not a compaction summary)."""
    return (m.role == "user" and not m.meta.get("tool_results") and not m.meta.get("summary")
            and not m.meta.get("skill_load"))


def skill_load_positions(msgs: list[Message], include_truncated: bool = False) -> dict[str, int]:
    """Latest full loads in active history, including successful read_skill tool results.

    A tool call alone is not a load: it may fail, be interrupted or have its output truncated.
    Reference-file reads do not load the skill's protocol either. Positions refer to the result,
    where its text actually lives. `include_truncated` also counts reads whose output was cut:
    the skill was loaded (it is in `loaded_skills`), but that copy doesn't hold its whole protocol.
    """
    calls = {c.id: c.input["name"] for m in msgs for c in m.tool_calls()
             if c.name == "read_skill" and not c.input.get("path") and c.input.get("name")}
    loaded = {}
    for i, m in enumerate(msgs):
        if name := m.meta.get("skill_load"):
            loaded[name] = i
        for b in m.content:
            if (isinstance(b, ToolResultBlock) and not b.is_error and b.tool_use_id in calls
                    and (include_truncated or "\n\n[Output cut at " not in b.as_text())):
                loaded[calls[b.tool_use_id]] = i
    return loaded


# ---------------------------------------------------------------------- cutting


def cut_candidates(msgs: list[Message]) -> list[int]:
    """Indexes where history may be cut (msgs[:i] summarized, msgs[i:] kept), mildest first.
    At a user turn, or inside a long turn at an assistant message that follows a user message:
    every tool call in the kept part then has its result in the kept part too."""
    turns = [i for i, m in enumerate(msgs) if is_user_turn(m)]
    asst = [i for i, m in enumerate(msgs) if m.role == "assistant" and i > 0 and msgs[i - 1].role == "user"]
    out = {turns[-k] for k in range(1, KEEP_RECENT_TURNS + 1) if len(turns) >= k and turns[-k] >= 2}
    out |= {asst[-n] for n in (KEEP_TOOL_EXCHANGES, 2, 1) if len(asst) >= n and asst[-n] >= 4}
    return sorted(c for c in out if _pairs_intact(msgs[c:]))


def _pairs_intact(keep: list[Message]) -> bool:
    """Every tool result in the kept part answers a tool call in the kept part (results of a stopped
    run are added after the next user message, so a cut there would orphan them)."""
    calls = {c.id for m in keep for c in m.tool_calls()}
    return all(b.tool_use_id in calls for m in keep for b in m.content if isinstance(b, ToolResultBlock))


def manual_cut(msgs: list[Message]) -> int | None:
    """Compact button: keep the last KEEP_RECENT_TURNS user turns, or inside one long turn the last
    KEEP_TOOL_EXCHANGES tool exchanges."""
    turns = [i for i, m in enumerate(msgs) if is_user_turn(m)]
    asst = [i for i, m in enumerate(msgs) if m.role == "assistant" and i > 0 and msgs[i - 1].role == "user"]
    for c in ([turns[-KEEP_RECENT_TURNS]] if len(turns) > KEEP_RECENT_TURNS else []) + (
            [asst[-KEEP_TOOL_EXCHANGES]] if len(asst) > KEEP_TOOL_EXCHANGES and asst[-KEEP_TOOL_EXCHANGES] >= 4 else []):
        if _pairs_intact(msgs[c:]):
            return c
    return None


def choose_cut(msgs: list[Message], tokens: Callable[[list[Message]], float], target: float) -> int | None:
    """The mildest cut whose kept part fits `target` tokens, else the most aggressive one."""
    cands = cut_candidates(msgs)
    for c in cands:
        if tokens(msgs[c:]) <= target:
            return c
    return cands[-1] if cands else None


# ------------------------------------------------------------------- summarizing


def transcript(old: list[Message]) -> str:
    lines = []
    for m in old:
        for b in m.content:
            if isinstance(b, TextBlock):
                who = "EARLIER SUMMARY" if m.meta.get("summary") else m.role.upper()
                lines.append(f"{who}: {b.text}")
            elif isinstance(b, ToolUseBlock):
                lines.append(f"TOOL CALL {b.name}: {json.dumps(b.input)[:600]}")
            elif isinstance(b, ToolResultBlock):
                lines.append(f"TOOL RESULT: {b.as_text()[:600]}")
            elif isinstance(b, (ImageBlock, FileBlock, AudioBlock)):
                lines.append(f"[{b.type} attachment: {b.name} item={b.item_id}]")
    text = "\n".join(lines)
    if len(text) > TRANSCRIPT_MAX:
        # Keep the head (the original goal and early decisions) and the tail (latest state).
        cut = len(text) - TRANSCRIPT_MAX
        text = (text[:TRANSCRIPT_HEAD] + f"\n[… {cut:,} characters from the middle of the conversation omitted …]\n"
                + text[-(TRANSCRIPT_MAX - TRANSCRIPT_HEAD):])
    return text


async def compact_messages(app: "AppState", sid: str, msgs: list[Message], cut: int, auto: bool = False) -> dict:
    """Summarize msgs[:cut] with claude.fast at low effort (through the adapter, so the effort gate
    and spend limits apply; usage recorded as role compact) and hide them from the model. The
    originals stay in history. If the kept part has no user turn, the latest one is quoted verbatim
    in the summary so the current request survives. Fires the pre_compact hook event first (both
    auto-compact and the Compact button come through here)."""
    s = app.store.get(sid)
    old, keep = msgs[:cut], msgs[cut:]
    model = app.config.resolve("claude.fast")
    mcfg = app.config.model(model)
    profile = app.config.profile_for(s, mcfg.provider)
    prov = app.providers.for_model(model, profile)
    app.usage.check(sid)
    hooks = getattr(app, "hooks", None)
    if hooks is not None and hooks.has("pre_compact"):  # e.g. a campaign saves its Active context first
        from ..features.hookbus import HookEvent
        from .tools import ToolContext

        await hooks.fire(HookEvent("pre_compact", ToolContext(app=app, session=s, run_id=f"compact:{sid}"),
                                   turn=hooks.turn(sid), extra={"auto": auto, "cut": cut, "messages": len(msgs)}))
    resp = await prov.complete(ChatRequest(model=model, effort="low", max_tokens=2000, show_thinking=False,
                                           system=COMPACT_PROMPT, messages=[Message.user(transcript(old))],
                                           metadata={"run_id": f"compact:{sid}"}))
    app.usage.record(provider=mcfg.provider, model=model, usage=resp.usage, session_id=sid, role="compact",
                     profile=profile, effort="low", latency_ms=resp.latency_ms)
    text = resp.text().strip() or "(No summary.)"
    if not any(is_user_turn(m) for m in keep):
        for m in reversed(old):
            if is_user_turn(m):
                g = m.text()
                text += GOAL_HEAD + "\n".join("> " + ln for ln in (g[:GOAL_MAX] + ("…" if len(g) > GOAL_MAX else ""))
                                             .splitlines())
                break
            if m.meta.get("summary") and GOAL_HEAD in m.text():  # compacted twice in one turn: carry it over
                text += GOAL_HEAD + m.text().split(GOAL_HEAD, 1)[1]
                break
    summary = Message(role="user", content=[TextBlock(text=text)],
                      meta={"summary": True, "summarized": len(old), **({"auto": True} if auto else {})})
    first_kept = keep[0].meta.get("created_at") if keep else None
    if first_kept is None and keep:
        first_kept = (app.db.one("SELECT created_at FROM messages WHERE id=?", [keep[0].id]) or {}).get("created_at")
    # App notices ("reply hit the output limit") aren't in `msgs` (the model never sees them); those
    # before the cut are hidden along with the turns they belonged to.
    notices = [m.id for m in app.store.messages(sid, include_compacted=False) if m.meta.get("notice")
               and (first_kept is None or (m.meta.get("created_at") or 0) < first_kept)]
    app.store.mark_compacted([m.id for m in old] + notices)
    reloads = []
    settings = app.store.get(sid)["settings"]
    if settings.get("skill_mode") == "progressive":
        from ..skills import pinned_skill_names, skill_load_text

        # Re-add a loaded skill whose text (a skill_load message or a read_skill result, even a
        # truncated one) was in the compacted part, unless a full copy survives in the kept part.
        # A truncated read alone never counts as that copy, so its protocol comes back whole.
        full = skill_load_positions(msgs)
        compacted = skill_load_positions(msgs[:cut], include_truncated=True)
        pinned = pinned_skill_names(settings)
        for name in dict.fromkeys(settings.get("loaded_skills", [])):
            if name not in pinned and name in compacted and full.get(name, -1) < cut:
                if body := skill_load_text(name):
                    reloads.append(Message(role="user", content=[TextBlock(text=body)], meta={"skill_load": name}))
    if reloads:
        from ..db import now

        boundary = first_kept if first_kept is not None else now()
        start = boundary - 0.0005
        app.store.add_message(sid, summary, created_at=start)
        for i, load in enumerate(reloads, 1):
            app.store.add_message(sid, load, created_at=start + i * 0.0005 / (len(reloads) + 1))
    else:
        app.store.add_message(sid, summary, created_at=(first_kept - 0.0005) if first_kept else None)
    # A kept part that starts with a user message follows our (user) summary: adapters merge
    # consecutive same-role messages, so that's fine.
    app.bus.publish("session.compacted", {"id": sid, "summarized": len(old), "auto": auto}, sid)
    return {"compacted": len(old)}


# ----------------------------------------------------------------- last resort


def stub_tool_results(msgs: list[Message], tokens: Callable[[list[Message]], float], budget: float,
                      keep_last: int = 1) -> tuple[list[Message], int]:
    """A copy of the history with the oldest tool output and attachments replaced by a short note
    until it fits `budget` (the last `keep_last` tool-result messages are cut down last). Only the
    outgoing request changes; the stored history keeps everything."""
    total = tokens(msgs)
    if total <= budget:
        return msgs, 0
    out = list(msgs)
    results = [i for i, m in enumerate(out) if any(isinstance(b, ToolResultBlock) for b in m.content)]
    media = [i for i, m in enumerate(out[:-1]) if any(isinstance(b, (ImageBlock, FileBlock, AudioBlock)) for b in m.content)]
    order = sorted(set(results[:-keep_last] if keep_last else results) | set(media)) + results[-keep_last:]
    n = 0
    for i in order:
        if total <= budget:
            break
        m = out[i]
        before = tokens([m])
        content = []
        for b in m.content:
            if isinstance(b, ToolResultBlock) and sum(sum(block_tokens(c)) for c in b.content) > 50:
                size = sum(sum(block_tokens(c)) for c in b.content)
                content.append(b.model_copy(update={"content": [TextBlock(text=STUB.format(n=size))]}))
                n += 1
            elif isinstance(b, (ImageBlock, FileBlock, AudioBlock)):
                content.append(TextBlock(text=f"[{b.type} '{b.name or ''}' removed to fit the context window]"))
                n += 1
            else:
                content.append(b)
        out[i] = m.model_copy(update={"content": content})
        total -= before - tokens([out[i]])
    return out, n
