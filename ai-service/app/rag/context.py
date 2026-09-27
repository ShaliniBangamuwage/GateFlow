from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContextEntry:
    source: str
    section: str
    content: str
    chunk_id: int | str | None
    similarity: float = 0.0

    def format_for_prompt(self) -> str:
        source_name = self.source or "unknown"
        section_name = self.section or "Document"
        chunk_label = self.chunk_id if self.chunk_id is not None else "unknown"
        return (
            f"src={source_name}; sec={section_name}; chunk={chunk_label}; text={self.content.strip()}"
        )


def build_context(rows: list[dict[str, Any]], *, max_chars: int = 4000, max_chunks: int = 5) -> list[ContextEntry]:
    seen: set[tuple[str, str, str, int | str | None, str]] = set()
    entries: list[ContextEntry] = []

    for row in rows:
        source = str(row.get("source_id") or row.get("source_name") or row.get("source") or "unknown")
        section = str(row.get("section") or (row.get("metadata") or {}).get("section") or "Document")
        content = str(row.get("content") or "")
        chunk_id = row.get("id") if row.get("id") is not None else row.get("chunk_index")
        marker = (source, section, content.strip(), chunk_id, str(row.get("tenant_id", "")))
        if marker in seen:
            continue
        seen.add(marker)
        similarity = float(row.get("similarity") or 0.0)
        entries.append(ContextEntry(source=source, section=section, content=content, chunk_id=chunk_id, similarity=similarity))

    entries.sort(key=lambda item: item.similarity, reverse=True)
    selected: list[ContextEntry] = []
    current_chars = 0
    for entry in entries[:max_chunks]:
        text = entry.format_for_prompt()
        if selected and current_chars + len(text) > max_chars:
            if current_chars < max_chars * 0.9:
                selected.append(entry)
                current_chars += len(text)
                continue
            break
        selected.append(entry)
        current_chars += len(text)
    return selected
