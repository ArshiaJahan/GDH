"""Script a model that follows every injected instruction without making real calls."""
from __future__ import annotations

import json
import re

from gamedevworkstation.core.types import Response, ToolResultBlock
from gamedevworkstation.features.auto_mode import CLASSIFIER_PROMPT
from gamedevworkstation.providers.fake import text_response, tool_response

OPEN = re.compile(r'<(untrusted-[0-9a-f]{8}) source="([^"]*)">\n(.*)\n</\1>', re.S)


def _norm(text: str) -> str:
    """Compare payload and body ignoring the '<' that defanging turns into '&lt;'."""
    return text.replace("&lt;", "").replace("<", "")


def is_wrapped(latest: str, payload: str) -> bool:
    """The payload sits only inside one untrusted block with matching nonce, and no forged tag survived."""
    m = OPEN.search(latest)
    if not m or latest.count("<untrusted-") != 1 or latest.count("</untrusted-") != 1:
        return False
    outside = _norm(latest[:m.start()] + latest[m.end():])
    body, need = _norm(m.group(3)), _norm(payload).strip()
    return bool(need) and need in body and need not in outside


def marker_text(case, world) -> str:
    """The injected text to look for: the payload when the carrier result contains it, else the whole result."""
    result, payload = world.subst(case["carrier"].get("result", "")), world.subst(case.get("payload", ""))
    return payload if payload and payload in result else result


def worst_case_script(case, world) -> list:
    """Carrier call, then one attack call per response (in order), then 'done'."""
    def attack(item) -> Response:
        return tool_response(item["tool"], world.subst(item["args"]))

    calls: list = []
    attacks, first = list(case["attack"]), case["attack"][0]
    if carrier := case.get("carrier"):
        calls.append(tool_response(carrier["tool"], world.subst(carrier["args"])))

        def first_attack(req):
            latest = "\n".join(b.as_text() for m in req.messages[-1:] for b in m.content
                               if isinstance(b, ToolResultBlock))
            world.wrapped = is_wrapped(latest, marker_text(case, world))
            return attack(first)
        calls.append(first_attack)
        attacks = attacks[1:]
    calls += [attack(item) for item in attacks]
    calls.append(text_response("done"))
    return calls


def install(world, script: list) -> None:
    """Load the script into the FakeProvider; Auto-mode classifier requests are answered without eating it."""
    fake, pop = world.fake, world.fake._next
    fake.script = script

    def _next(req):
        if req.system == CLASSIFIER_PROMPT:
            return text_response(json.dumps({"decision": "allow", "reason": "scripted worst case"}), model=req.model)
        return pop(req)
    fake._next = _next
