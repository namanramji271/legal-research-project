"""Shared ChromaDB embedding configuration for the judgment corpus."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from chromadb import Documents, EmbeddingFunction, Embeddings
from chromadb.utils.embedding_functions import register_embedding_function

MODEL_NAME = "all-MiniLM-L6-v2"
COLLECTION_NAME = "judgment_chunks"
CHROMA_DB_PATH = Path(__file__).resolve().parent / "data" / "chroma_db"


@register_embedding_function
class JudgmentEmbeddingFunction(EmbeddingFunction[Documents]):
    """Embed documents and queries with the same locally loaded MiniLM model."""

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise SystemExit(
                "Missing embedding dependencies. Install with: "
                "pip install -r backend/requirements.txt"
            ) from error
        self.model_name = model_name
        self._model = SentenceTransformer(model_name)

    def __call__(self, input: Documents) -> Embeddings:
        """Implement Chroma's embedding-function protocol for documents and queries."""
        if not input:
            return []
        return self._model.encode(
            input,
            batch_size=32,
            show_progress_bar=False,
            convert_to_numpy=True,
        ).tolist()

    @classmethod
    def name(cls) -> str:
        """Return Chroma's stable registry name for this embedding function."""
        return "judgment-minilm"

    def get_config(self) -> dict[str, Any]:
        """Return only serializable settings needed to recreate this function."""
        return {"model_name": self.model_name}

    @classmethod
    def build_from_config(
        cls, config: dict[str, Any]
    ) -> "JudgmentEmbeddingFunction":
        """Recreate the function when Chroma restores collection configuration."""
        return cls(model_name=str(config.get("model_name", MODEL_NAME)))


@lru_cache(maxsize=1)
def get_embedding_function() -> JudgmentEmbeddingFunction:
    """Load MiniLM once per process and reuse it for every Chroma operation."""
    return JudgmentEmbeddingFunction()
