"""Item index: every artifact, media item, file and link that enters a session.

FTS5 covers title, filename, URL and extracted text (PDF/doc text, page titles,
transcripts). Items are attributed to the provider/model that produced them, or that
received them when the user attached them.
"""
from __future__ import annotations

import json
import mimetypes
import re
import sqlite3
from pathlib import Path
from typing import Any

from .core.types import AudioBlock, FileBlock, ImageBlock, Message, TextBlock, ToolResultBlock, new_id
from .db import DB, now
from .events import EventBus

URL_RX = re.compile(r"https?://[^\s<>\]\)\"'`]+")
TEXT_EXT = {".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".toml", ".yaml", ".yml", ".csv",
            ".html", ".css", ".sh", ".rs", ".go", ".java", ".c", ".h", ".cpp", ".swift", ".sql", ".xml", ".svg"}
ARTIFACT_EXT = {".html": "html", ".htm": "html", ".svg": "svg", ".md": "markdown", ".mmd": "diagram",
                ".mermaid": "diagram"}
CODE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java", ".c", ".cpp", ".swift", ".sh", ".sql",
            ".css", ".rb", ".kt"}

TAB_KIND = {"artifacts": "artifact", "media": "media", "files": "file", "links": "link"}


def classify(path: str | Path, mime: str | None = None) -> tuple[str, str]:
    """(kind, subtype) for a file."""
    p = Path(path)
    ext = p.suffix.lower()
    mime = mime or mimetypes.guess_type(p.name)[0] or ""
    if ext in ARTIFACT_EXT:  # before MIME: an SVG is a diagram artifact, not a photo
        return "artifact", ARTIFACT_EXT[ext]
    if mime.startswith(("image/", "audio/", "video/")):
        return "media", mime.split("/")[0]
    if ext == ".pdf":
        return "file", "pdf"
    if ext in CODE_EXT:
        return "file", "code"
    if ext in {".csv", ".json", ".xlsx", ".parquet", ".tsv"}:
        return "file", "data"
    return "file", "document"


OOXML_EXT = {".docx", ".pptx", ".xlsx"}
OOXML_MAX_PART = 30_000_000   # uncompressed bytes of one XML part we are willing to parse
OOXML_MAX_TOTAL = 80_000_000  # ... and of all parts together (zip bombs)
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _num(name: str) -> int:
    m = re.search(r"(\d+)\.xml$", name)
    return int(m.group(1)) if m else 0


def _ooxml_text(p: Path, limit: int) -> str | None:
    """Text of a .docx / .pptx / .xlsx with the standard library only (they are zips of XML):
    Word paragraphs, slide text in slide order, and spreadsheet cells (shared strings resolved)
    one row per line. Stops at `limit` characters; oversized parts are skipped."""
    import zipfile
    from xml.etree import ElementTree as ET

    ext = p.suffix.lower()
    out: list[str] = []
    size = 0
    budget = OOXML_MAX_TOTAL

    def add(s: str) -> bool:
        nonlocal size
        out.append(s)
        size += len(s) + 1
        return size < limit

    with zipfile.ZipFile(p) as z:
        infos = {i.filename: i for i in z.infolist()}

        def parts(names: list[str]):
            nonlocal budget
            for n in names:
                info = infos.get(n)
                if info is None or info.file_size > OOXML_MAX_PART or info.file_size > budget:
                    continue
                budget -= info.file_size
                with z.open(info) as f:
                    yield n, f

        if ext == ".docx":
            names = ["word/document.xml"] + sorted(n for n in infos if re.fullmatch(r"word/(footnotes|endnotes)\.xml", n))
            for _n, f in parts(names):
                para: list[str] = []
                for ev, el in ET.iterparse(f, events=("end",)):
                    if el.tag == _W + "t" and el.text:
                        para.append(el.text)
                    elif el.tag == _W + "tab":
                        para.append("\t")
                    elif el.tag in (_W + "br", _W + "cr"):
                        para.append("\n")
                    elif el.tag == _W + "p":
                        if para and not add("".join(para)):
                            break
                        para = []
                        el.clear()
        elif ext == ".pptx":
            slides = sorted((n for n in infos if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=_num)
            for n, f in parts(slides):
                lines: list[str] = []
                para: list[str] = []
                for ev, el in ET.iterparse(f, events=("end",)):
                    if el.tag == _A + "t" and el.text:
                        para.append(el.text)
                    elif el.tag == _A + "p":
                        if para:
                            lines.append("".join(para))
                        para = []
                if lines and not add(f"Slide {_num(n)}\n" + "\n".join(lines) + "\n"):
                    break
        elif ext == ".xlsx":
            shared: list[str] = []
            for _n, f in parts(["xl/sharedStrings.xml"]):
                for ev, el in ET.iterparse(f, events=("end",)):
                    if el.tag == _S + "si":
                        shared.append("".join(t.text or "" for t in el.iter(_S + "t")))
                        el.clear()
            sheets = sorted((n for n in infos if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)), key=_num)
            done = False
            for n, f in parts(sheets):
                if not add(f"Sheet {_num(n)}"):
                    break
                for ev, el in ET.iterparse(f, events=("end",)):
                    if el.tag != _S + "row":
                        continue
                    cells: list[str] = []
                    for c in el.iter(_S + "c"):
                        t, v = c.get("t"), c.find(_S + "v")
                        if t == "s" and v is not None and (v.text or "").isdigit():
                            i = int(v.text or 0)
                            cells.append(shared[i] if i < len(shared) else "")
                        elif t == "inlineStr":
                            cells.append("".join(x.text or "" for x in c.iter(_S + "t")))
                        elif v is not None and v.text is not None:
                            cells.append(v.text)
                    el.clear()
                    if any(cells) and not add("\t".join(cells)):
                        done = True
                        break
                if done:
                    break
    text = "\n".join(out).strip()
    return text[:limit] if text else None


def extract_text(path: str | Path, mime: str | None = None, limit: int = 200_000) -> str | None:
    p = Path(path)
    try:
        if p.suffix.lower() in OOXML_EXT:
            return _ooxml_text(p, limit)
        if p.suffix.lower() == ".pdf":
            from pypdf import PdfReader

            r = PdfReader(str(p))
            return "\n".join((pg.extract_text() or "") for pg in r.pages[:200])[:limit]
        if p.suffix.lower() in TEXT_EXT or (mime or "").startswith("text/"):
            t = p.read_text(errors="replace")[:limit]
            if p.suffix.lower() in (".html", ".htm"):
                m = re.search(r"<title>(.*?)</title>", t, re.S | re.I)
                body = re.sub(r"<[^>]+>", " ", t)
                return ((m.group(1).strip() + "\n") if m else "") + re.sub(r"\s+", " ", body)[:limit]
            return t
    except Exception:
        return None
    return None


def fts_query(q: str) -> str:
    """User text → safe FTS5 query: every term as a prefix match, ANDed."""
    terms = re.findall(r"[\w\-\.]+", q)
    return " ".join(f'"{t}"*' for t in terms) or '""'


class ItemIndex:
    def __init__(self, db: DB, bus: EventBus):
        self.db, self.bus = db, bus

    def add(self, *, kind: str, source: str, session_id: str | None = None, message_id: str | None = None,
            subtype: str | None = None, provider: str | None = None, model: str | None = None,
            title: str | None = None, path: str | None = None, url: str | None = None,
            size: int | None = None, mime: str | None = None, extracted_text: str | None = None,
            meta: dict | None = None, parent_id: str | None = None) -> str | None:
        filename = Path(path).name if path else None
        if path and size is None and Path(path).exists():
            size = Path(path).stat().st_size
        version = 1
        if parent_id:
            prev = self.db.one("SELECT version FROM items WHERE id=?", [parent_id])
            version = (prev or {}).get("version", 0) + 1
        elif kind == "artifact" and path and session_id:
            # Re-writing the same artifact path makes a new version.
            prev = self.db.one("SELECT id, version FROM items WHERE session_id=? AND path=? AND kind='artifact' "
                               "AND deleted=0 ORDER BY version DESC LIMIT 1", [session_id, path])
            if prev:
                parent_id, version = prev["id"], prev["version"] + 1
        iid = new_id("itm_")
        row = {"id": iid, "session_id": session_id, "message_id": message_id, "kind": kind, "subtype": subtype,
               "provider": provider, "model": model, "source": source, "title": title or filename or url,
               "filename": filename, "path": path, "url": url, "size": size, "mime": mime,
               "extracted_text": extracted_text, "meta": json.dumps(meta or {}), "version": version,
               "parent_id": parent_id, "created_at": now()}
        try:
            self.db.insert("items", row)
        except sqlite3.IntegrityError:  # duplicate link in this session
            return None
        self.bus.publish("item.created", self.get(iid), session_id)
        return iid

    def add_file(self, path: str | Path, *, source: str, session_id: str | None, provider: str | None,
                 model: str | None, message_id: str | None = None, title: str | None = None,
                 meta: dict | None = None, extracted_text: str | None = None, kind: str | None = None,
                 subtype: str | None = None) -> str | None:
        p = Path(path)
        mime = mimetypes.guess_type(p.name)[0]
        k, st = classify(p, mime)
        return self.add(kind=kind or k, subtype=subtype or st, source=source, session_id=session_id,
                        message_id=message_id, provider=provider, model=model, title=title, path=str(p),
                        mime=mime, extracted_text=extracted_text if extracted_text is not None else extract_text(p, mime),
                        meta=meta)

    def index_message(self, sid: str, msg: Message, *, provider: str | None, model: str | None,
                      source: str) -> list[str]:
        """Links mentioned in text, plus attachments not yet indexed."""
        ids: list[str] = []
        texts = []
        for b in msg.content:
            if isinstance(b, TextBlock):
                texts.append(b.text)
                for c in b.citations or []:
                    if u := c.get("url"):
                        if i := self.add(kind="link", subtype="cited", source=source, session_id=sid,
                                         message_id=msg.id, provider=provider, model=model, url=u,
                                         title=c.get("title") or u):
                            ids.append(i)
            elif isinstance(b, ToolResultBlock):
                texts.append(b.as_text())
            elif isinstance(b, (ImageBlock, AudioBlock, FileBlock)) and not b.item_id and b.path:
                if i := self.add_file(b.path, source=source, session_id=sid, provider=provider, model=model,
                                      message_id=msg.id, title=b.name):
                    b.item_id = i
                    ids.append(i)
        for t in texts:
            for u in URL_RX.findall(t):
                u = u.rstrip(".,;:!?")
                if i := self.add(kind="link", subtype="mentioned", source=source, session_id=sid, message_id=msg.id,
                                 provider=provider, model=model, url=u, title=u):
                    ids.append(i)
        return ids

    # --------------------------------------------------------------------- query

    def get(self, iid: str) -> dict | None:
        r = self.db.one("SELECT i.*, s.title AS session_title FROM items i LEFT JOIN sessions s ON s.id=i.session_id "
                        "WHERE i.id=?", [iid])
        if r:
            r["meta"] = json.loads(r["meta"] or "{}")
        return r

    def _filters(self, f: dict[str, Any]) -> tuple[str, list[Any]]:
        where, p = ["i.deleted=0"], []
        if f.get("tab") in TAB_KIND:
            where.append("i.kind=?")
            p.append(TAB_KIND[f["tab"]])
        for col in ("kind", "provider", "model", "source", "subtype"):
            v = f.get(col)
            if v and v != "all":
                vals = v if isinstance(v, list) else [v]
                where.append(f"i.{col} IN ({','.join('?' * len(vals))})")
                p.extend(vals)
        sids = f.get("sessions") or ([f["session_id"]] if f.get("session_id") else None)
        if sids:
            where.append(f"i.session_id IN ({','.join('?' * len(sids))})")
            p.extend(sids)
        if f.get("since"):
            where.append("i.created_at >= ?")
            p.append(float(f["since"]))
        if f.get("until"):
            where.append("i.created_at <= ?")
            p.append(float(f["until"]))
        return " AND ".join(where), p

    def list(self, **f: Any) -> list[dict]:
        where, p = self._filters(f)
        rows = self.db.all(
            "SELECT i.*, s.title AS session_title FROM items i LEFT JOIN sessions s ON s.id=i.session_id "
            f"WHERE {where} ORDER BY i.created_at DESC LIMIT ?", [*p, int(f.get("limit", 2000))])
        for r in rows:
            r["meta"] = json.loads(r["meta"] or "{}")
        return rows

    def grouped(self, **f: Any) -> list[dict]:
        """Items grouped by session: sessions by last activity, items newest first.
        Artifacts show only their latest version (history via versions())."""
        items = self.list(**f)
        if f.get("tab") == "artifacts":
            seen, latest = set(), []
            for it in items:  # newest first, so the first per path wins
                key = (it["session_id"], it["path"] or it["id"])
                if key not in seen:
                    seen.add(key)
                    latest.append(it)
            items = latest
        groups: dict[str | None, dict] = {}
        act = {r["id"]: r["updated_at"] for r in self.db.all("SELECT id, updated_at FROM sessions")}
        for it in items:
            g = groups.setdefault(it["session_id"], {"session_id": it["session_id"],
                                                     "session_title": it.get("session_title") or "(no session)",
                                                     "last_activity": act.get(it["session_id"], 0), "items": []})
            g["items"].append(it)
        out = sorted(groups.values(), key=lambda g: g["last_activity"], reverse=True)
        for g in out:
            g["count"] = len(g["items"])
        return out

    def versions(self, iid: str) -> list[dict]:
        it = self.get(iid)
        if not it:
            return []
        return self.db.all("SELECT id, version, created_at, model, size FROM items WHERE session_id=? AND path=? "
                           "AND kind='artifact' AND deleted=0 ORDER BY version DESC", [it["session_id"], it["path"]])

    def search(self, q: str, **f: Any) -> list[dict]:
        where, p = self._filters(f)
        rows = self.db.all(
            "SELECT i.*, s.title AS session_title, "
            "highlight(items_fts, 0, '<mark>', '</mark>') AS hl_title, "
            "highlight(items_fts, 2, '<mark>', '</mark>') AS hl_url, "
            "snippet(items_fts, 3, '<mark>', '</mark>', '…', 16) AS hl_text, bm25(items_fts) AS score "
            "FROM items_fts JOIN items i ON i.rowid = items_fts.rowid "
            "LEFT JOIN sessions s ON s.id=i.session_id "
            f"WHERE items_fts MATCH ? AND {where} ORDER BY score LIMIT ?",
            [fts_query(q), *p, int(f.get("limit", 200))])
        groups: dict[str | None, dict] = {}
        for r in rows:
            r["meta"] = json.loads(r["meta"] or "{}")
            groups.setdefault(r["session_id"], {"session_id": r["session_id"],
                                                "session_title": r.get("session_title") or "(no session)",
                                                "items": []})["items"].append(r)
        return list(groups.values())

    def delete(self, iid: str) -> None:
        self.db.update("items", "id", iid, {"deleted": 1})
        self.bus.publish("item.deleted", {"id": iid})
