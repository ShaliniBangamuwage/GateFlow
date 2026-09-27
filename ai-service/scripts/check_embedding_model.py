"""Download/initialize the configured local embedding model and report its dimension."""

from app.rag.embeddings import EmbeddingProvider


def main() -> None:
    provider = EmbeddingProvider()
    document = provider.embed_text("GateFlow rate limiting returns HTTP 429.")
    query = provider.embed_query("Why are too many requests rejected?")
    assert len(document) == len(query) == provider.dimension
    print(
        f"model={provider.model_name}; dimension={provider.dimension}; "
        f"document_vector={len(document)}; query_vector={len(query)}"
    )


if __name__ == "__main__":
    main()
