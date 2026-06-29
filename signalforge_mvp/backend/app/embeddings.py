"""Embedding generation service with fallback to keyword search.

Tries OpenAI API first, then a local sentence-transformers model, then
falls back to None. When no embedding service is available, the search
router transparently falls back to the existing keyword search.
"""

import hashlib
import warnings
from typing import Any

from app.config import config

EMBEDDING_DIM = 1536


class EmbeddingService:
    """Generate text embeddings with graceful fallback."""

    def __init__(self) -> None:
        self._openai_client: Any | None = None
        self._local_model: Any | None = None
        self._mode: str | None = None
        self._init()

    def _init(self) -> None:
        # Try OpenAI first
        openai_key = config.OPENAI_API_KEY
        if openai_key:
            try:
                import openai
                self._openai_client = openai.OpenAI(api_key=openai_key)
                self._mode = "openai"
                return
            except Exception as exc:
                warnings.warn(f"OpenAI embedding init failed: {exc}", stacklevel=2)

        # Try local sentence-transformers
        try:
            from sentence_transformers import SentenceTransformer
            self._local_model = SentenceTransformer("all-MiniLM-L6-v2")
            self._mode = "local"
            return
        except Exception as exc:
            warnings.warn(f"Local embedding model init failed: {exc}", stacklevel=2)

        # No embedding service available
        self._mode = None

    def is_available(self) -> bool:
        return self._mode is not None

    def embed(self, text: str) -> list[float] | None:
        if not self._mode:
            return None

        if self._mode == "openai" and self._openai_client:
            try:
                resp = self._openai_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=text[:8192],
                )
                return resp.data[0].embedding
            except Exception as exc:
                warnings.warn(f"OpenAI embedding failed: {exc}", stacklevel=2)
                return None

        if self._mode == "local" and self._local_model:
            try:
                return self._local_model.encode(text).tolist()
            except Exception as exc:
                warnings.warn(f"Local embedding failed: {exc}", stacklevel=2)
                return None

        return None

    def embed_batch(self, texts: list[str]) -> list[list[float]] | None:
        if not self._mode:
            return None

        if self._mode == "openai" and self._openai_client:
            try:
                trimmed = [t[:8192] for t in texts]
                resp = self._openai_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=trimmed,
                )
                return [d.embedding for d in resp.data]
            except Exception as exc:
                warnings.warn(f"OpenAI batch embedding failed: {exc}", stacklevel=2)
                return None

        if self._mode == "local" and self._local_model:
            try:
                embeddings = self._local_model.encode(texts)
                return [e.tolist() for e in embeddings]
            except Exception as exc:
                warnings.warn(f"Local batch embedding failed: {exc}", stacklevel=2)
                return None

        return None


embedding_service = EmbeddingService()
