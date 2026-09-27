import pytest

from app.rag.chunking import chunk_markdown


def test_chunking_preserves_sections_paragraphs_and_metadata() -> None:
    content = "# Rate Limits\n\n" + ("Token buckets refill gradually. " * 30) + "\n\n## Retry behavior\n\nClients should honor Retry-After."

    chunks = chunk_markdown(content, max_chars=500, overlap_chars=60)

    assert len(chunks) >= 2
    assert chunks[0].section == "Rate Limits"
    assert any(chunk.section == "Retry behavior" for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(len(chunk.content) <= 500 for chunk in chunks)
    assert all(chunk.content.strip() for chunk in chunks)


def test_chunking_is_deterministic_and_splits_long_paragraphs() -> None:
    content = "# Long section\n\n" + ("word " * 1_000)

    first = chunk_markdown(content, max_chars=400, overlap_chars=50)
    second = chunk_markdown(content, max_chars=400, overlap_chars=50)

    assert first == second
    assert len(first) > 1
    assert all(len(chunk.content) <= 400 for chunk in first)
    assert all(chunk.section == "Long section" for chunk in first)


def test_chunking_rejects_bad_limits() -> None:
    with pytest.raises(ValueError, match="at least 200"):
        chunk_markdown("text", max_chars=100)
    with pytest.raises(ValueError, match="smaller"):
        chunk_markdown("text", max_chars=200, overlap_chars=200)
