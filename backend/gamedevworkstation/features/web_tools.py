"""Web research tools for the main agent and any subagent they're granted to
(Claude or Codex): `web_search` runs a short claude.fast request with Anthropic's basic
server-side web search tool and returns cited findings; `web_fetch` reads one public page
(safe_fetch: every redirect hop checked, connects to the checked address).
Cited and fetched URLs land in the item index (Links tab)."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import httpx
from fastapi import APIRouter, Body, FastAPI, HTTPException, Response

from ..agent.tools import ToolContext, ToolOutput, obj
from ..core.types import Usage
from ..providers.anthropic_provider import usage_from_wire
from ..providers.base import compute_cost
from ..safe_fetch import UnsafeURL, safe_fetch

if TYPE_CHECKING:
    from ..app import AppState

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
SEARCH_USD = 0.01  # $10 per 1,000 searches
MAX_FETCH_BYTES = 3_000_000
MAX_IMAGE_BYTES = 10_000_000
# Raster formats only: an SVG can carry scripts and external references.
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "image/bmp"}
SEARCH_PROMPT = ("Search the web and answer: {q}\n\nReply in at most 12 tight bullets. Every claim needs a source. "
                 "Prefer primary sources. No preamble.")


def html_to_text(html: str) -> tuple[str, str]:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    body = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer)[^>]*>.*?</\1>", " ", html)
    body = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", body)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"&nbsp;", " ", body)
    body = re.sub(r"&amp;", "&", body)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n\s*\n+", "\n\n", body).strip()
    return title, body


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    @S.tools.add("web_search", "Search the web (via Claude's web search) and get cited findings. Grant it to research "
                 "subagents together with web_fetch.",
                 obj({"query": {"type": "string"}, "allowed_domains": {"type": "array", "items": {"type": "string"}}},
                     ["query"]), read_only=True)
    async def web_search(ctx: ToolContext, a: dict) -> ToolOutput:
        S.usage.check(ctx.session_id)
        model = S.config.resolve("claude.fast")
        profile = S.config.profile_for(ctx.session, "anthropic")
        prov = S.providers.chat("anthropic", profile)
        tool = dict(WEB_SEARCH_TOOL)
        if a.get("allowed_domains"):
            tool["allowed_domains"] = a["allowed_domains"]
        try:
            msg = await prov.client.messages.create(  # type: ignore[attr-defined]
                model=model, max_tokens=4000, tools=[tool], output_config={"effort": "low"},
                messages=[{"role": "user", "content": SEARCH_PROMPT.format(q=a["query"])}])
        except Exception as e:  # noqa: BLE001
            return ToolOutput(f"web search failed: {e}", is_error=True)
        usage = usage_from_wire(msg.usage)
        searches = getattr(getattr(msg.usage, "server_tool_use", None), "web_search_requests", 0) or 0
        usage.cost_usd = compute_cost(S.config.model(model), usage) + searches * SEARCH_USD
        S.usage.record(provider="anthropic", model=model, usage=usage, session_id=ctx.session_id, role="tool",
                       run_id=ctx.run_id, effort="low", feature="web_search", profile=profile)
        lines, sources = [], {}
        for b in msg.content:
            if b.type == "text":
                lines.append(b.text)
                for c in getattr(b, "citations", None) or []:
                    url = getattr(c, "url", None)
                    if url:
                        sources[url] = getattr(c, "title", None) or url
        for url, title in sources.items():
            S.items.add(kind="link", subtype="cited", source="tool", session_id=ctx.session_id,
                        message_id=ctx.message_id, provider=ctx.provider, model=ctx.model, url=url, title=title)
        text = "".join(lines).strip() or "No results."
        if sources:
            text += "\n\nSources:\n" + "\n".join(f"- {t}: {u}" for u, t in sources.items())
        return ToolOutput(text, untrusted=f"web_search:{a['query']}")

    @S.tools.add("web_fetch", "Fetch one public web page and return its text (and title).",
                 obj({"url": {"type": "string"}, "max_chars": {"type": "integer"}}, ["url"]), read_only=True)
    async def web_fetch(ctx: ToolContext, a: dict) -> ToolOutput:
        url = a["url"].strip()
        src = f"web_fetch:{url}"
        try:
            r = await safe_fetch(url, max_bytes=MAX_FETCH_BYTES, user_agent="GameDevWorkstation/0.1 (personal agent)")
        except UnsafeURL as e:
            msg = str(e)
            if msg.startswith("That address"):
                msg = "That address is local or private; web_fetch only reads public pages."
            return ToolOutput(msg, is_error=True)
        except (httpx.HTTPError, ValueError) as e:
            return ToolOutput(f"fetch failed: {e}", is_error=True)
        ctype, status, size = r.content_type, r.status, len(r.content)
        raw = r.content.decode("utf-8", "replace")
        if "html" in ctype:
            title, text = html_to_text(raw)
        elif ctype.startswith("text/") or "json" in ctype or "xml" in ctype:
            title, text = "", raw
        else:
            return ToolOutput(f"{status} {ctype or 'unknown type'}: not a text page ({size} bytes).", is_error=status >= 400)
        S.items.add(kind="link", subtype="fetched", source="tool", session_id=ctx.session_id, message_id=ctx.message_id,
                    provider=ctx.provider, model=ctx.model, url=url, title=title or url,
                    extracted_text=(title + "\n" + text[:5000]).strip())
        limit = min(int(a.get("max_chars") or 20000), 100_000)
        body = text[:limit] + (f"\n…[{len(text) - limit} more characters]" if len(text) > limit else "")
        return ToolOutput(f"{status} {title}\n\n{body}".strip(), is_error=status >= 400, untrusted=src)

    # ---------------------------------------------------------- click-to-load images

    @api.post("/remote-image")
    async def remote_image(body: dict = Body(...)) -> Response:
        """A remote image in chat Markdown, fetched only after the user pressed Load on its
        placeholder. The UI shows it from a blob: URL, so the window itself never contacts
        the remote host (the CSP allows no https: images) and nothing loads on render."""
        url = str(body.get("url") or "").strip()
        try:
            r = await safe_fetch(url, max_bytes=MAX_IMAGE_BYTES, truncate=False,
                                 user_agent="GameDevWorkstation/0.1 (image preview)", headers={"Accept": "image/*"})
        except UnsafeURL as e:
            raise HTTPException(400, str(e)) from e
        except (httpx.HTTPError, ValueError) as e:
            raise HTTPException(502, f"Couldn't load the image: {e}") from e
        ctype = r.content_type.split(";", 1)[0].strip().lower()
        if r.status >= 400:
            raise HTTPException(502, f"The image server answered {r.status}.")
        if ctype not in IMAGE_TYPES:
            raise HTTPException(415, f"Not an image ({ctype or 'unknown type'}).")
        return Response(r.content, media_type=ctype, headers={"X-Content-Type-Options": "nosniff",
                                                              "Cache-Control": "no-store"})
