FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .
COPY scripts ./scripts
COPY deploy ./deploy
COPY tests ./tests
RUN useradd --create-home --uid 10001 memory && mkdir -p /models && chown memory /models
USER memory
ENV EMBEDDING_CACHE=/models
EXPOSE 8765
CMD ["uvicorn", "agent_memory.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8765"]
