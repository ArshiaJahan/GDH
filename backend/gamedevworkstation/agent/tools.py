"""Tool framework: specs offered to models, handlers, path scoping and permission checks."""
from __future__ import annotations

import asyncio
import mimetypes
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from ..core.types import ImageBlock, TextBlock, ToolResultBlock, ToolSpec, new_id

if TYPE_CHECKING:
    from ..app import AppState


class ToolDenied(Exception):
    pass


# Approval kinds Plan only mode refuses outright (as the Agent SDK harness's gate() does), before
# any allowlist rule is looked at.
PLAN_REFUSED_KINDS = {"edit": "edits", "delete": "deletes", "merge": "merges", "run_command": "commands",
                      "command": "commands"}


@dataclass
class ToolOutput:
    text: str
    is_error: bool = False
    items: list[str] = field(default_factory=list)
    images: list[ImageBlock] = field(default_factory=list)
    # Where the text came from when it is outside content (a web page, search results, an MCP
    # server, a subagent's report), e.g. "web_fetch:https://…". finalize_output wraps it in
    # <untrusted source="…"> markers; the system prompts say such content is data, not instructions.
    untrusted: str | None = None

    def to_block(self, tool_use_id: str) -> ToolResultBlock:
        return ToolResultBlock(tool_use_id=tool_use_id, is_error=self.is_error,
                               content=[TextBlock(text=self.text or "(no output)"), *self.images])


@dataclass
class ToolContext:
    app: "AppState"
    session: dict
    run_id: str
    role: str = "main"  # main | subagent | hook (an action a hook runs; see features/hookbus.hook_context)
    provider: str = "anthropic"
    model: str = ""
    message_id: str | None = None
    extra_roots: list[Path] = field(default_factory=list)  # e.g. a subagent's worktree
    cwd_override: Path | None = None
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    # What the user already consented to for this context, by approval kind, as exact subjects
    # (e.g. {"run_command": {"<command line>"}, "mcp": {"<server>__<tool>"}}). Only hook contexts
    # (hookbus.hook_context) carry any; for the main agent and subagents it's always empty.
    consent: dict[str, set[str]] = field(default_factory=dict)

    def consented(self, kind: str, subject: str) -> bool:
        """True if `subject` is exactly one of the consented subjects of `kind`."""
        return subject in self.consent.get(kind, ())

    @property
    def session_id(self) -> str:
        return self.session["id"]

    @property
    def folder(self) -> Path | None:
        if self.cwd_override:
            return self.cwd_override
        f = self.session.get("folder")
        return Path(f).expanduser().resolve() if f else None

    @property
    def roots(self) -> list[Path]:
        if self.role != "main":
            # A subagent sees only its own worktree, or the session folder if it has none.
            return [r.resolve() for r in self.extra_roots] or ([self.folder] if self.folder else [])
        roots = [r.resolve() for r in self.extra_roots]
        if self.folder:
            roots.append(self.folder)
        roots.append(self.app.worktrees_root(self.session_id).resolve())
        return roots

    def within_roots(self, p: Path) -> bool:
        full = p.resolve()
        return any(full == r or r in full.parents for r in self.roots)

    def resolve_path(self, p: str, *, write: bool = False) -> Path:
        """Resolve a tool-supplied path, refusing anything outside the session folder
        and its worktrees (symlinks included). write=True (writes, edits, deletes) also refuses
        git metadata: anything inside a `.git` folder, or a worktree's `.git` file."""
        if not self.folder:
            raise ToolDenied("This session has no folder (chat only). Pick a folder in the Environment card.")
        raw = Path(p).expanduser()
        full = (raw if raw.is_absolute() else self.folder / raw).resolve()
        for root in self.roots:
            if full == root or root in full.parents:
                if write and (in_git_metadata(full) or in_git_metadata(raw)):
                    raise ToolDenied(GIT_WRITE_REFUSED.format(path=p))
                return full
        raise ToolDenied(f"{p} is outside the session folder")

    @property
    def mode(self) -> str:
        return self.session.get("mode", "ask")

    async def approve(self, kind: str, subject: str, payload: dict[str, Any]) -> None:
        """Ask the user unless the mode or allowlist already permits it. Plan only mode is checked
        first: an allowlist rule never lets an edit, delete, merge or command through in Plan."""
        app = self.app
        if self.mode == "plan" and kind in PLAN_REFUSED_KINDS:
            raise ToolDenied(f"Session is in Plan only mode: no {PLAN_REFUSED_KINDS[kind]}. "
                             "Describe the change instead.")
        if self.consented(kind, subject) or app.approvals.allowlisted(kind, subject):
            return
        if kind == "edit" and self.mode == "accept_edits":
            return
        res = await app.approvals.ask(self.session_id, kind, {"subject": subject, "run_id": self.run_id,
                                                               "role": self.role, **payload})
        if res["status"] != "approved":
            raise ToolDenied(f"User declined: {subject}")


# Writing git metadata is how a file edit becomes command execution: hooks run on the app's own
# `git worktree add` / commit / merge, and .git/config can name programs (core.fsmonitor, filters,
# diff drivers) that `git diff` or `git status` start. Agent file tools may read it but never write it.
GIT_WRITE_REFUSED = ("{path} is git metadata (.git); agent file tools can't write or delete there. "
                     "Use git commands (they ask first) if this is really needed.")
# Code points HFS+ ignores in file names, so `.g<U+200C>it` is `.git` there (git's is_hfs_dotgit).
_HFS_IGNORED = dict.fromkeys([*range(0x200C, 0x2010), *range(0x202A, 0x202F), *range(0x206A, 0x2070), 0xFEFF])


def in_git_metadata(path: Path | str) -> bool:
    """True if any component of path is `.git` (case-insensitive, as on macOS volumes)."""
    return any(part.translate(_HFS_IGNORED).casefold() == ".git" for part in Path(path).parts)


Handler = Callable[[ToolContext, dict[str, Any]], Awaitable[ToolOutput]]


@dataclass
class Tool:
    spec: ToolSpec
    handler: Handler
    main_only: bool = False  # e.g. spawn_subagent: subagents are one level deep
    always: bool = False  # offered even when a caller grants a list of tools (read_output)
    # Offered only when when(session) is true (e.g. campaign tools only in campaign sessions), so
    # inactive features cost no tool-spec tokens. Gets the session dict; a raising `when` counts as
    # false. specs() without a session leaves such tools out; run() refuses them when false.
    when: Callable[[dict], bool] | None = None

    def offered(self, session: dict | None) -> bool:
        """Whether `when` allows this tool for `session` (always true without a `when`)."""
        if self.when is None:
            return True
        if session is None:
            return False
        try:
            return bool(self.when(session))
        except Exception:  # noqa: BLE001 — a broken condition hides the tool
            return False


class ToolRegistry:
    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {}

    def add(self, name: str, description: str, schema: dict[str, Any], *, read_only: bool = False,
            main_only: bool = False, always: bool = False,
            when: Callable[[dict], bool] | None = None) -> Callable[[Handler], Handler]:
        def deco(fn: Handler) -> Handler:
            self.tools[name] = Tool(ToolSpec(name=name, description=description, input_schema=schema,
                                             read_only=read_only), fn, main_only, always, when)
            return fn

        return deco

    def register(self, tool: Tool) -> None:
        self.tools[tool.spec.name] = tool

    def specs(self, names: list[str] | None = None, *, role: str = "main",
              session: dict | None = None) -> list[ToolSpec]:
        """Specs to offer: `names` (plus `always` tools) when given, without main_only tools for
        other roles, and without tools whose `when(session)` is false (see Tool.when)."""
        out = []
        for n, t in self.tools.items():
            if names is not None and n not in names and not t.always:
                continue
            if role != "main" and t.main_only:
                continue
            if not t.offered(session):
                continue
            out.append(t.spec)
        return out

    async def run(self, ctx: ToolContext, name: str, args: dict[str, Any],
                  allowed: list[str] | None = None) -> ToolOutput:
        t = self.tools.get(name)
        if t is None or (allowed is not None and name not in allowed and not t.always) or \
                (ctx.role != "main" and t.main_only) or not t.offered(ctx.session):
            return ToolOutput(f"Tool '{name}' is not available here.", is_error=True)
        try:
            return finalize_output(ctx, name, await t.handler(ctx, args))
        except ToolDenied as e:
            return ToolOutput(str(e), is_error=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — tool failures go back to the model
            return ToolOutput(f"{type(e).__name__}: {e}", is_error=True)


# ------------------------------------------------------------- output limits

# Every tool result is stored, re-sent on every later turn and copied into events, so one huge
# result costs on every turn after it. Defaults; override in config [orchestrator]
# tool_output_chars / tool_output_images.
TOOL_OUTPUT_CHARS = 30_000
TOOL_OUTPUT_IMAGES = 4
IMAGE_MAX_B64 = 5_000_000       # per image, base64 characters (the Anthropic API's 5 MB limit)
IMAGES_TOTAL_B64 = 10_000_000   # all images of one result
# Characters that render as nothing (zero-width, joiners, bidi controls, soft hyphen, BOM).
_INVISIBLE_CHARS = r"\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u202a-\u202e\u2060-\u206f\u3164\ufe00-\ufe0f\ufeff\uffa0"
_INVISIBLE = re.compile(f"[{_INVISIBLE_CHARS}]")
_GAP = f"[\\s/\\\\{_INVISIBLE_CHARS}]*"  # spaces, slashes and invisible characters between `<` and the name
_LETTER_GAP = f"[{_INVISIBLE_CHARS}]*"
# `<` and its look-alikes: fullwidth, small, angle brackets, math angle brackets, the encoded forms.
_LT = r"(?:<|\uff1c|\ufe64|\u2329|\u3008|\u27e8|\u2039|&lt;|&#0*60;|&#x0*3c;)"
UNTRUSTED_TAG = re.compile(_LT + _GAP + _LETTER_GAP.join("untrusted"), re.I)


def tool_outputs_dir() -> Path:
    from ..config import data_dir

    d = data_dir() / "tool_outputs"
    d.mkdir(exist_ok=True)
    return d


def output_limits(ctx: ToolContext) -> tuple[int, int]:
    o = getattr(getattr(ctx.app, "config", None), "orchestrator", None) or {}
    chars = int(o.get("tool_output_chars") or TOOL_OUTPUT_CHARS)
    images = TOOL_OUTPUT_IMAGES if o.get("tool_output_images") is None else int(o["tool_output_images"])
    return max(chars, 2000), max(images, 0)


def wrap_untrusted(text: str, source: str) -> str:
    """Mark outside content as data: `<untrusted-NONCE source="…">…</untrusted-NONCE>`, with a fresh
    random nonce per call, so the content can't guess (and close) its own block. Anything inside it
    that looks like an untrusted tag (any spacing, slashes, invisible characters, fullwidth or other
    look-alike `<`) is defanged too."""
    src = re.sub(r"[\"<>\r\n\u2028\u2029]", "", _INVISIBLE.sub("", source))[:200]
    tag = f"untrusted-{secrets.token_hex(4)}"
    body = UNTRUSTED_TAG.sub(lambda m: "&lt;" + m.group(0)[1:], text)
    return f'<{tag} source="{src}">\n{body}\n</{tag}>'


def _image_size(img: ImageBlock) -> int:
    if img.data:
        return len(img.data)
    try:
        return Path(img.path).stat().st_size * 4 // 3 if img.path else 0
    except OSError:
        return 0


def finalize_output(ctx: ToolContext, name: str, out: ToolOutput) -> ToolOutput:
    """The one place every tool result passes before it reaches a model (built-in tools via
    ToolRegistry.run, MCP tools via MCPManager.call): cap the text and the images, keep the
    overflow in data_dir/tool_outputs as an item that read_output can page through, and wrap
    outside content in untrusted markers."""
    max_chars, max_images = output_limits(ctx)
    app = ctx.app
    text, notes = out.text, []
    items = list(out.items)

    keep: list[ImageBlock] = []
    extra: list[ImageBlock] = []
    total = 0
    for img in out.images:
        size = _image_size(img)
        if len(keep) < max_images and size <= IMAGE_MAX_B64 and total + size <= IMAGES_TOTAL_B64:
            keep.append(img)
            total += size
        else:
            extra.append(img)
    if extra:
        saved = []
        for img in extra:
            try:
                ext = mimetypes.guess_extension(img.media_type) or ".bin"
                p = tool_outputs_dir() / f"{new_id('img_')}{ext}"
                p.write_bytes(img.load_bytes())
                if iid := app.items.add_file(p, source="tool", session_id=ctx.session_id, provider=ctx.provider,
                                             model=ctx.model, message_id=ctx.message_id, title=f"{name} image",
                                             meta={"tool": name}):
                    saved.append(iid)
                    items.append(iid)
            except Exception:  # noqa: BLE001 — a broken image must not fail the tool call
                continue
        notes.append(f"[{len(extra)} more image(s) not shown (over {max_images} images or too large)"
                     + (f"; saved as items {', '.join(saved)}]" if saved else "]"))

    if len(text) > max_chars:
        full = text
        try:
            p = tool_outputs_dir() / f"{new_id('out_')}.txt"
            p.write_text(full, encoding="utf-8")
            iid = app.items.add(kind="file", subtype="tool_output", source="tool", session_id=ctx.session_id,
                                message_id=ctx.message_id, provider=ctx.provider, model=ctx.model,
                                title=f"{name} output ({len(full):,} characters)", path=str(p),
                                size=p.stat().st_size, mime="text/plain", extracted_text=full[:200_000],
                                meta={"tool": name, "chars": len(full), "untrusted": out.untrusted})
        except OSError:
            iid = None
        text = full[:max_chars]
        if iid:
            items.append(iid)
            notes.append(f"[Output cut at {max_chars:,} of {len(full):,} characters. The full output is item {iid}; "
                         f'read the rest with read_output(id="{iid}", offset={max_chars}).]')
        else:
            notes.append(f"[Output cut at {max_chars:,} of {len(full):,} characters.]")

    if out.untrusted:
        text = wrap_untrusted(text, out.untrusted)
    if notes:
        text = text + "\n\n" + "\n".join(notes)
    return ToolOutput(text, is_error=out.is_error, items=items, images=keep, untrusted=out.untrusted)


def obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}
