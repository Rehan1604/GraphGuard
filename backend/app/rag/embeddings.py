"""Step 2 of RAG: turn text into vectors (lists of numbers) so that similar meanings land close together.

Two embedders, same interface:
  * FastEmbedEmbedder - a small neural sentence-embedding model (default BAAI/bge-small-en-v1.5) run locally with
    ONNX. Understands paraphrase ("money returned to where it began" ~ "circular flow"). Needs `pip install fastembed`
    and a one-time model download. No GPU, no API key.
  * LsaEmbedder - TF-IDF followed by a low-rank projection (latent semantic analysis), fitted on the library itself.
    Works offline with nothing to download and is fully deterministic. Weaker on paraphrase; it is what the tests use.

Every vector is length-normalised, so a dot product IS the cosine similarity."""
from __future__ import annotations

import logging
from typing import Protocol

import numpy as np

log = logging.getLogger("graphguard.rag")
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    name: str
    min_score: float  # similarities below this are treated as "not related" (depends on the embedder's scale)

    def fit(self, texts: list[str]) -> None: ...
    def embed_documents(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


def _normalise(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(norms == 0, 1.0, norms)


class LsaEmbedder:
    name = "lsa"
    min_score = 0.25

    def __init__(self, n_components: int = 48):
        self.n_components = n_components
        self._vec = None
        self._svd = None

    def fit(self, texts: list[str]) -> None:
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._vec = TfidfVectorizer(stop_words="english", sublinear_tf=True, ngram_range=(1, 2), strip_accents="unicode")
        x = self._vec.fit_transform(texts)
        k = max(2, min(self.n_components, x.shape[0] - 1, x.shape[1] - 1))
        self._svd = TruncatedSVD(n_components=k, random_state=0, n_iter=10).fit(x)

    def _embed(self, texts: list[str]) -> np.ndarray:
        if self._vec is None or self._svd is None:
            raise RuntimeError("LsaEmbedder must be fitted on the library first")
        return _normalise(self._svd.transform(self._vec.transform(texts)))

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text])[0]


class FastEmbedEmbedder:
    min_score = 0.40

    def __init__(self, model_name: str):
        from fastembed import TextEmbedding  # imported here so the app runs without the package

        self.model_name = model_name
        self.name = f"fastembed:{model_name}"
        self._model = TextEmbedding(model_name=model_name)

    def fit(self, texts: list[str]) -> None:  # a pre-trained model needs no fitting
        return None

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return _normalise(np.array(list(self._model.embed(texts))))

    def embed_query(self, text: str) -> np.ndarray:
        prefix = BGE_QUERY_PREFIX if "bge" in self.model_name.lower() else ""
        return _normalise(np.array(list(self._model.embed([prefix + text]))))[0]


def build_embedder(preference: str, model_name: str, corpus: list[str]) -> tuple[Embedder, str]:
    """Return (embedder, plain-words note about which one is in use and why)."""
    if preference in ("auto", "fastembed"):
        try:
            emb = FastEmbedEmbedder(model_name)
            return emb, f"Neural embeddings: {model_name} (local, via fastembed)."
        except Exception as exc:  # package missing, no network for the first download, etc.
            if preference == "fastembed":
                raise
            log.warning("neural embedder unavailable (%s: %s); using the offline embedder", type(exc).__name__, exc)
            reason = f"neural embedder unavailable ({type(exc).__name__})"
    else:
        reason = "offline embedder selected by configuration"
    lsa = LsaEmbedder()
    lsa.fit(corpus)
    return lsa, f"Offline latent-semantic embedder ({reason}). Install fastembed for neural embeddings."
