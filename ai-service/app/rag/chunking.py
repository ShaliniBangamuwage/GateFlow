"""Deterministic paragraph-aware document splitting for knowledge ingestion."""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_MAX_CHARS = 1_800
DEFAULT_OVERLAP_CHARS = 240


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    content: str
    section: str


def chunk_markdown(
    text: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[TextChunk]:
    """Keep headings/paragraphs together where possible and overlap boundaries."""
    if max_chars < 200:
        raise ValueError("max_chars must be at least 200")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be non-negative and smaller than max_chars")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    sections: list[tuple[str, str]] = []
    current_heading = "Document"
    current_parts: list[str] = []
    for line in normalized.splitlines():
        heading = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            if current_parts:
                sections.append((current_heading, "\n".join(current_parts).strip()))
            current_heading = heading.group(2).strip()
            current_parts = [line.strip()]
        else:
            current_parts.append(line)
    if current_parts:
        sections.append((current_heading, "\n".join(current_parts).strip()))

    chunks: list[TextChunk] = []
    for heading, section_text in sections:
        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", section_text) if paragraph.strip()]
        current = ""
        for paragraph in paragraphs:
            for piece in _split_oversized_paragraph(paragraph, max_chars):
                candidate = f"{current}\n\n{piece}".strip() if current else piece
                if len(candidate) <= max_chars:
                    current = candidate
                    continue
                if current:
                    chunks.append(TextChunk(len(chunks), current, heading))
                    overlap = current[-overlap_chars:].strip() if overlap_chars else ""
                    while overlap and len(overlap) + 2 + len(piece) > max_chars:
                        overlap = overlap[1:].lstrip()
                    current = f"{overlap}\n\n{piece}".strip() if overlap else piece
                else:
                    current = piece
        if current:
            chunks.append(TextChunk(len(chunks), current, heading))
    return chunks


def _split_oversized_paragraph(paragraph: str, max_chars: int) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    parts: list[str] = []
    remaining = paragraph
    while len(remaining) > max_chars:
        boundary = remaining.rfind(" ", 0, max_chars + 1)
        if boundary < max_chars // 2:
            boundary = max_chars
        parts.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    if remaining:
        parts.append(remaining)
    return parts