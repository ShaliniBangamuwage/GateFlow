from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.rag.context import ContextEntry, build_context
from app.rag.search import search_knowledge_base_pgvector


class EmbedderLike(Protocol):
    def embed_query(self, text: str) -> list[float]: ...


class LLMLike(Protocol):
    def generate(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class EvidenceSource:
    source: str
    section: str
    chunk_id: int | str | None


@dataclass
class GroundedAnswer:
    answer: str
    sources: list[EvidenceSource] = field(default_factory=list)
    grounded: bool = False


class _PromptBuilder:
    @staticmethod
    def build(question: str, tenant_id: str, entries: list[ContextEntry]) -> str:
        evidence = "\n\n".join(entry.format_for_prompt() for entry in entries)
        if not entries:
            evidence = "No GateFlow evidence was retrieved for this tenant and question."

        return (
            "You are a GateFlow assistant. Use only the provided GateFlow evidence.\n"
            "- Do not invent GateFlow configuration or operational claims.\n"
            "- Distinguish evidence from interpretation.\n"
            "- State when evidence is insufficient.\n"
            "- Preserve tenant boundaries and never reveal secrets.\n"
            "- If the evidence is insufficient, answer with: 'I don't have sufficient GateFlow evidence to answer that.'\n\n"
            f"Tenant: {tenant_id}\n\n"
            f"Question: {question}\n\n"
            "Evidence:\n"
            f"{evidence}\n\n"
            "Return a concise grounded answer in plain text."
        )


def generate_grounded_answer(
    *,
    question: str,
    tenant_id: str,
    store: Any,
    embedder: EmbedderLike | None = None,
    llm: LLMLike | None = None,
    limit: int = 5,
    max_chars: int = 4000,
    max_chunks: int = 5,
) -> GroundedAnswer:
    if not question.strip():
        raise ValueError("question must be a non-empty string")
    if not tenant_id.strip():
        raise ValueError("tenant_id is required")

    embedder = embedder or _IdentityEmbedder()
    llm = llm or _IdentityLLM()

    rows = store.search(tenant_id=tenant_id, query_vector=embedder.embed_query(question), limit=limit)
    entries = build_context(rows, max_chars=max_chars, max_chunks=max_chunks)
    if not entries:
        return GroundedAnswer(
            answer="I don't have sufficient GateFlow evidence to answer that.",
            sources=[],
            grounded=False,
        )

    prompt = _PromptBuilder.build(question, tenant_id, entries)
    answer = llm.generate(prompt)
    sources = [
        EvidenceSource(source=entry.source, section=entry.section, chunk_id=entry.chunk_id) for entry in entries
    ]
    return GroundedAnswer(answer=answer, sources=sources, grounded=True)


class _IdentityEmbedder:
    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0] if text.strip() else [0.0, 0.0]


class _IdentityLLM:
    def generate(self, prompt: str) -> str:
        return prompt
