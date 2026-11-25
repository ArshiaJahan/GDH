"""Best-effort tripwire for secrets sent in outbound text, not DLP: a model can split or paraphrase a secret."""
from __future__ import annotations

import base64
import binascii
import fnmatch
import json
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlsplit

SECRET_FILE_GLOBS = (".env", ".env.*", ".envrc", "*.pem", "*_rsa", "*_ed25519", "id_rsa*", "id_ed25519*", "credentials", "credentials.*",
                     "*.p12", "*.pfx", "*.keystore", "*.key", ".netrc", ".npmrc", ".git-credentials", ".pgpass", "secrets.*")
# Templates carry no secrets by convention (the Auto rules use the same list).
SECRET_FILE_TEMPLATES = (".env.example", ".env.sample", ".env.template", ".env.dist")
MAX_TAINT_PER_SESSION = 200
_SECRET_KEY_NAME = re.compile(r"PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|PRIVATE_KEY|CREDENTIAL", re.IGNORECASE)
_B64_PIECE = re.compile(r"[A-Za-z0-9_+/=-]{16,}")
_URL_SPLIT = re.compile(r"[?&=/#;+]")
_BASE64_RUN = re.compile(r"(?<![A-Za-z0-9_+/=-])[A-Za-z0-9_+/=-]{16,}(?![A-Za-z0-9_+/=-])")


def is_secret_file(path: str | Path) -> bool:
    """Recognize secret file names without depending on their directory."""
    name = Path(path).name.lower()
    if name in SECRET_FILE_TEMPLATES:
        return False
    return any(fnmatch.fnmatchcase(name, pattern.lower()) for pattern in SECRET_FILE_GLOBS)


def _json_values(node, key: str = "") -> Iterable[tuple[str, str]]:
    """(key, string value) pairs from a parsed JSON document."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _json_values(v, str(k))
    elif isinstance(node, list):
        for v in node:
            yield from _json_values(v, key)
    elif isinstance(node, str):
        yield key, node


def _try_json(text: str):
    text = text.strip()
    if text[:1] in ("{", "["):
        try:
            return json.loads(text)
        except ValueError:
            return None
    return None


def extract_secret_values(text: str) -> set[str]:
    """Collect long secret-like assignments, known keys and PEM body lines."""
    from .features.skill_assistant import SECRET_VALUE, _looks_secret

    values = {m.group(0) for m in SECRET_VALUE.finditer(text)}
    docs = [_try_json(text)]
    for line in text.splitlines():
        positions = [p for p in (line.find("="), line.find(":")) if p >= 0]
        if positions:
            at = min(positions)
            value = line[at + 1:].strip().strip("\"' ")
            named = bool(_SECRET_KEY_NAME.search(line[:at]))
            candidates = [value]
            doc = _try_json(line[at + 1:])  # a JSON value after the key
            if doc is not None:
                docs.append(doc)
            if (trimmed := re.sub(r"[\s,;}\]]+$", "", value).strip("\"' ")) != value:  # trailing JSON/INI punctuation
                candidates.append(trimmed)
            if re.search(r"\s#", value):  # an inline dotenv comment is not part of the value
                candidates.append(re.split(r"\s#", value, maxsplit=1)[0].strip().strip("\"' "))
            for cand in candidates:
                if (len(cand) >= 12 and (_looks_secret(cand) or SECRET_VALUE.search(cand))) or (named and len(cand) >= 8):
                    values.add(cand)
    for doc in docs:
        for key, val in _json_values(doc) if doc is not None else ():
            if (len(val) >= 12 and (_looks_secret(val) or SECRET_VALUE.search(val))) or (
                    _SECRET_KEY_NAME.search(key) and len(val) >= 8):
                values.add(val)
    if "-----BEGIN" in text:
        in_body = False
        for line in text.splitlines():
            if line.startswith("-----BEGIN"):
                in_body = True
                continue
            if line.startswith("-----END"):
                in_body = False
                continue
            if in_body and len(line.strip()) >= 20:
                values.add(line.strip())
    return values


def secret_name(path) -> Path | None:
    """The requested or the symlink-resolved path, whichever has a secret file name (else None)."""
    for candidate in (Path(path), _resolved(path)):
        if candidate is not None and is_secret_file(candidate):
            return candidate
    return None


def _resolved(path) -> Path | None:
    try:
        return Path(path).resolve()
    except (OSError, ValueError, RuntimeError):
        return None


def taint_secret_path(app, session_id: str, path) -> int:
    """Taint the values of one file if it is a secret file by its requested or resolved name."""
    named = secret_name(path)
    if named is None:
        return 0
    try:
        with Path(path).open(encoding="utf-8", errors="replace") as fh:
            return taint_file(app, session_id, named, fh.read(200000))
    except (OSError, ValueError):
        return 0


def search_targets(root, patterns: Iterable[str] = (), limit: int = 2000) -> list[Path]:
    """Secret files a Grep/Glob call can reach: the file itself, or, for a folder, secret files whose
    name or relative path matches one of the call's glob patterns (a search without a glob skips hidden files)."""
    import os

    root = Path(root)
    if root.is_file():
        return [root] if secret_name(root) else []
    pats = [p for p in patterns if p]
    if not pats or not root.is_dir():
        return []
    out, seen = [], 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", ".venv", "__pycache__"}]
        for f in filenames:
            seen += 1
            if seen > limit:
                return out
            full = Path(dirpath) / f
            rel = str(full.relative_to(root))
            if any(fnmatch.fnmatchcase(rel, p) or fnmatch.fnmatchcase(f, p.rsplit("/", 1)[-1]) for p in pats) and secret_name(full):
                out.append(full)
    return out


def taint_store(app) -> dict[str, set[str]]:
    """Keep discovered values only in the app's in-memory session state."""
    return app.__dict__.setdefault("_egress_taint", {})


def taint_file(app, session_id: str, path, text: str) -> int:
    """Remember newly read secret-file values, bounded per session."""
    if not is_secret_file(path):
        return 0
    store = taint_store(app)
    values = store.setdefault(session_id, set())
    room = max(0, MAX_TAINT_PER_SESSION - len(values))
    added = set(extract_secret_values(text)) - values
    selected = set(list(added)[:room])
    values.update(selected)
    return len(selected)


def variants(text: str) -> list[str]:
    """Expand common transport encodings without retaining malformed decodes."""
    out = [text]
    current = text
    for _ in range(2):
        decoded = unquote(current)
        if decoded == current:
            break
        out.append(decoded)
        current = decoded
    out.append(text.replace("+", " "))
    candidates = []
    for source in dict.fromkeys([text, *out]):  # the original and every URL-decoded form
        candidates += [m.group(0) for m in _BASE64_RUN.finditer(source)]
        candidates += [p for p in _URL_SPLIT.split(source) if len(p) >= 16 and _B64_PIECE.fullmatch(p)]  # ?d=<base64>
    for encoded in dict.fromkeys(candidates):
        for decoder in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                raw = decoder(encoded + "=" * (-len(encoded) % 4))
                out.append(raw.decode("utf-8"))
            except (binascii.Error, ValueError, UnicodeDecodeError):
                continue
    return list(dict.fromkeys(out))


def scan_text(text: str, tainted: Iterable[str] = (), extra_patterns: Iterable[re.Pattern] = ()) -> list[str]:
    """Return safe labels for detected secrets; never include matched values."""
    from .features.skill_assistant import SECRET_VALUE

    found: list[str] = []
    for candidate in variants(text):
        if SECRET_VALUE.search(candidate) and "a provider API key" not in found:
            found.append("a provider API key")
        if any(pattern.search(candidate) for pattern in extra_patterns) and "matches a custom pattern" not in found:
            found.append("matches a custom pattern")
        if any(value and value in candidate for value in tainted) and "a value read from .env this session" not in found:
            found.append("a value read from .env this session")
    return found


def scan_value(value, tainted=(), extra_patterns=()) -> list[str]:
    """Scan strings throughout nested tool arguments, including dictionary keys."""
    findings: list[str] = []
    if isinstance(value, dict):
        items = (item for pair in value.items() for item in pair)
        for item in items:
            findings.extend(scan_value(item, tainted, extra_patterns))
    elif isinstance(value, (list, tuple)):
        for item in value:
            findings.extend(scan_value(item, tainted, extra_patterns))
    elif isinstance(value, str):
        findings.extend(scan_text(value, tainted, extra_patterns))
    return list(dict.fromkeys(findings))


def check_url(app, session_id: str, url: str, extra_patterns=()) -> str | None:
    """Refuse URLs that carry detected values in any URL component."""
    findings = scan_text(url, taint_store(app).get(session_id, ()), extra_patterns)
    try:
        parts = urlsplit(url)
        components = [parts.hostname or "", parts.path, parts.query, parts.fragment]
        findings = list(dict.fromkeys(findings + sum((scan_text(c, taint_store(app).get(session_id, ()), extra_patterns) for c in components), [])))
    except ValueError:
        pass
    if findings:
        return f"Refused: this URL carries {', '.join(findings)} (egress check). If you meant to send it, ask the user to do it."
    return None


def check_args(app, session_id: str, args: dict, extra_patterns=()) -> str | None:
    """Refuse nested tool arguments containing detected values."""
    findings = scan_value(args, taint_store(app).get(session_id, ()), extra_patterns)
    if findings:
        return f"Refused: the arguments carry {', '.join(findings)} (egress check). If you meant to send it, ask the user to do it."
    return None
