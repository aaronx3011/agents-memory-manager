import threading
import time


class Embedder:
    """Lazy, shared ONNX model. Corpus and queries use the exact same generation."""

    def __init__(self, settings):
        self.model_name = settings.embedding_model
        self.cache = settings.embedding_cache
        self._model = None
        self._lock = threading.Lock()
        self.last_error = None
        self.retry_after = 0

    def _load_locked(self):
        # The caller must already hold self._lock. locked() is an advisory
        # guard (true for any holder) that catches the reintroduced
        # non-reentrant deadlock pattern of double acquisition.
        assert self._lock.locked()
        if time.monotonic() < self.retry_after:
            raise RuntimeError("Embedding provider cooling down")
        try:
            if self._model is None:
                from fastembed import TextEmbedding
                self._model = TextEmbedding(
                    model_name=self.model_name, cache_dir=self.cache, threads=2,
                )
        except Exception as exc:
            self.last_error = type(exc).__name__
            self.retry_after = time.monotonic() + 30
            raise

    def embed(self, text):
        return self.embed_batch([text])[0]

    def embed_batch(self, texts):
        with self._lock:
            self._load_locked()
            try:
                # pgvector's psycopg adapter binds numpy arrays, not plain lists.
                import numpy as np
                vectors = [np.asarray(vector, dtype=np.float32)
                           for vector in self._model.embed(list(texts))]
                for vector in vectors:
                    if len(vector) != 384:
                        raise ValueError("This schema requires a 384-dimensional model")
                self.last_error = None
                return vectors
            except Exception as exc:
                self.last_error = type(exc).__name__
                self.retry_after = time.monotonic() + 30
                raise

    def token_counts(self, texts, fallback=None):
        """Tokenizer token counts including special tokens, or the deterministic
        fallback estimate when the model cannot load. Callers must treat both as
        upper-bound planning data, never exact client-model budgets."""
        with self._lock:
            self._load_locked()
            tokenizer = getattr(self._model.model, "tokenizer", None)
        if tokenizer is None:
            if fallback is None:
                raise RuntimeError("Tokenizer unavailable for token counting")
            return fallback(texts)
        return [len(tokenizer.encode(text).ids) for text in texts]

    @property
    def ready(self):
        return self._model is not None and self.last_error is None
