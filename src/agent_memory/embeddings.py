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

    def embed(self, text):
        with self._lock:
            if time.monotonic() < self.retry_after:
                raise RuntimeError("Embedding provider cooling down")
            try:
                if self._model is None:
                    from fastembed import TextEmbedding
                    self._model = TextEmbedding(
                        model_name=self.model_name, cache_dir=self.cache, threads=2,
                    )
                vector = next(self._model.embed([text]))
                if len(vector) != 384:
                    raise ValueError("This schema requires a 384-dimensional model")
                self.last_error = None
                return vector
            except Exception as exc:
                self.last_error = type(exc).__name__
                self.retry_after = time.monotonic() + 30
                raise

    @property
    def ready(self):
        return self._model is not None and self.last_error is None
