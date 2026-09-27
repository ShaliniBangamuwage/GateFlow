import numpy as np
import pytest

from app.rag.embeddings import EmbeddingProvider, cosine_similarity


class FakeEmbeddingModel:
    def embed(self, texts):
        return [self.vector(text) for text in texts]

    def query_embed(self, text):
        return [self.vector(text)]

    @staticmethod
    def vector(text):
        return [float(sum(text.encode("utf-8"))) or 1.0, float(len(text))]


def test_cosine_similarity_matches_transparent_definition() -> None:
    similarity = cosine_similarity([1, 2], [3, 4])

    expected = 11 / (np.sqrt(5) * 5)
    assert similarity == pytest.approx(expected)
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1)


def test_cosine_similarity_rejects_invalid_shapes_and_zero_vectors() -> None:
    with pytest.raises(ValueError, match="equal lengths"):
        cosine_similarity([1], [1, 2])
    with pytest.raises(ValueError, match="zero vector"):
        cosine_similarity([0, 0], [1, 1])


def test_provider_exposes_text_document_query_and_measured_dimension() -> None:
    provider = EmbeddingProvider(model_name="fake", model=FakeEmbeddingModel())

    assert provider.dimension is None
    document_vectors = provider.embed_documents(["rate limit", "gateway route"])
    query_vector = provider.embed_query("429 overload")
    assert len(document_vectors) == 2
    assert len(document_vectors[0]) == len(query_vector) == 2
    assert provider.dimension == 2
    assert provider.embed_text("health check") == FakeEmbeddingModel.vector("health check")


def test_provider_rejects_empty_text_and_bad_model_output() -> None:
    provider = EmbeddingProvider(model_name="fake", model=FakeEmbeddingModel())
    with pytest.raises(ValueError, match="non-empty"):
        provider.embed_text("  ")

    class BadModel:
        def embed(self, texts):
            return [[1.0], [1.0, 2.0]]

        def query_embed(self, text):
            return [[1.0]]

    with pytest.raises(ValueError, match="inconsistent"):
        EmbeddingProvider(model_name="bad", model=BadModel()).embed_documents(["a", "b"])