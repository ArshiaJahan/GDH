"""Data policy: files the user marked sensitive only reach providers listed in
[data_policy].sensitive_allowed. Applied to every model request (history included), to
read_file / get_item, and to ElevenLabs uploads."""
from __future__ import annotations

import json
from pathlib import Path

from .config import Config
from .core.types import AudioBlock, FileBlock, ImageBlock, Message, TextBlock, ToolResultBlock
from .db import DB

WITHHELD = "[{name}: withheld — marked sensitive, and the data policy doesn't allow sending it to {provider}]"


class DataPolicy:
    def __init__(self, db: DB, config: Config):
        self.db, self.config = db, config

    def allows(self, provider: str) -> bool:
        return provider in (self.config.data_policy.get("sensitive_allowed") or [])

    def _sensitive_ids(self) -> set[str]:
        return {r["id"] for r in self.db.all("SELECT id, meta FROM items WHERE deleted=0 AND meta LIKE '%sensitive%'")
                if json.loads(r["meta"] or "{}").get("sensitive")}

    def _sensitive_paths(self) -> set[str]:
        out = set()
        for r in self.db.all("SELECT path, meta FROM items WHERE deleted=0 AND path IS NOT NULL AND meta LIKE '%sensitive%'"):
            if json.loads(r["meta"] or "{}").get("sensitive"):
                out.add(str(Path(r["path"]).resolve()))
        return out

    def item_allowed(self, item_id: str | None, provider: str) -> bool:
        return not item_id or self.allows(provider) or item_id not in self._sensitive_ids()

    def allows_path(self, path: Path, provider: str) -> bool:
        return self.allows(provider) or str(path.resolve()) not in self._sensitive_paths()

    def filter_messages(self, messages: list[Message], provider: str) -> list[Message]:
        """Copy of the history with sensitive attachments replaced by a note."""
        if self.allows(provider):
            return messages
        ids, paths = self._sensitive_ids(), self._sensitive_paths()
        if not ids and not paths:
            return messages

        def blocked(b) -> bool:
            if not isinstance(b, (ImageBlock, AudioBlock, FileBlock)):
                return False
            return (b.item_id in ids) or (b.path is not None and str(Path(b.path).resolve()) in paths)

        def note(b) -> TextBlock:
            return TextBlock(text=WITHHELD.format(name=b.name or b.type, provider=provider))

        out = []
        for m in messages:
            if not any(blocked(b) or (isinstance(b, ToolResultBlock) and any(blocked(c) for c in b.content))
                       for b in m.content):
                out.append(m)
                continue
            content = []
            for b in m.content:
                if blocked(b):
                    content.append(note(b))
                elif isinstance(b, ToolResultBlock):
                    content.append(b.model_copy(update={"content": [note(c) if blocked(c) else c for c in b.content]}))
                else:
                    content.append(b)
            out.append(m.model_copy(update={"content": content}))
        return out
