import os
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Settings:
    database_url: str
    admin_token: str
    owner_id: UUID
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_cache: str = "/models"
    worker_enabled: bool = True
    extraction_base_url: str = ""
    extraction_api_key: str = ""
    extraction_model: str = ""

    @classmethod
    def from_env(cls):
        token = os.environ["MEMORY_ADMIN_TOKEN"]
        if len(token) < 32:
            raise ValueError("MEMORY_ADMIN_TOKEN must have at least 32 characters")
        return cls(
            database_url=os.environ["DATABASE_URL"],
            admin_token=token,
            owner_id=UUID(os.environ["MEMORY_OWNER_ID"]),
            embedding_model=os.getenv("EMBEDDING_MODEL", cls.embedding_model),
            embedding_cache=os.getenv("EMBEDDING_CACHE", cls.embedding_cache),
            worker_enabled=os.getenv("WORKER_ENABLED", "true").lower() == "true",
            extraction_base_url=os.getenv("EXTRACTION_BASE_URL", ""),
            extraction_api_key=os.getenv("EXTRACTION_API_KEY", ""),
            extraction_model=os.getenv("EXTRACTION_MODEL", ""),
        )
