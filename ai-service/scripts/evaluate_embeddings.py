"""Check controlled semantic similarity ordering for the configured local model."""

from app.rag.embeddings import EmbeddingProvider, cosine_similarity


EXAMPLES = {
    "query": "Why am I receiving too many requests?",
    "related": "HTTP 429 means the rate limit was exceeded. The token bucket refills over time; clients should honor Retry-After.",
    "unrelated": "A sourdough loaf needs flour, water, and a warm place to rise.",
}


def main() -> None:
    provider = EmbeddingProvider()
    query = provider.embed_query(EXAMPLES["query"])
    related = provider.embed_text(EXAMPLES["related"])
    unrelated = provider.embed_text(EXAMPLES["unrelated"])
    related_similarity = cosine_similarity(query, related)
    unrelated_similarity = cosine_similarity(query, unrelated)
    print(f"model={provider.model_name}")
    print(f"dimension={provider.dimension}")
    print(f"related_cosine={related_similarity:.6f}")
    print(f"unrelated_cosine={unrelated_similarity:.6f}")
    print(f"related_ranks_higher={related_similarity > unrelated_similarity}")
    if related_similarity <= unrelated_similarity:
        raise SystemExit("controlled semantic ordering check failed")


if __name__ == "__main__":
    main()
