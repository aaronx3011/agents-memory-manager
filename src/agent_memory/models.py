from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MemoryType = Literal["episodic", "semantic", "procedural", "decision", "preference"]
Status = Literal["candidate", "active", "superseded", "expired", "disputed"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectInput(StrictModel):
    name: str = Field(min_length=1, max_length=150)
    repo_url: str | None = Field(default=None, max_length=1000)
    aliases: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("name", "repo_url", mode="before")
    @classmethod
    def trim_identity(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, value):
        aliases = list(dict.fromkeys(alias.strip() for alias in value))
        if any(not alias or len(alias) > 2000 for alias in aliases):
            raise ValueError("Aliases must contain 1–2000 non-whitespace characters")
        return aliases


class Source(StrictModel):
    kind: Literal["user", "repository", "task", "session", "document", "test"]
    reference: str = Field(min_length=1, max_length=2000)
    version: str | None = Field(default=None, max_length=200)
    excerpt: str | None = Field(default=None, max_length=2000)


class MemoryInput(StrictModel):
    project_id: UUID | None = None
    type: MemoryType
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=20000)
    sources: list[Source] = Field(min_length=1, max_length=20)
    evidence: Literal["inferred", "reported", "verified"] = "reported"
    status: Status = "active"
    verified_at: datetime | None = None
    review_after: datetime | None = None
    tags: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def check_evidence(self):
        if self.evidence == "verified" and self.verified_at is None:
            raise ValueError("Verified memories require verified_at and supporting sources")
        for value in (self.verified_at, self.review_after):
            if value is not None and value.tzinfo is None:
                raise ValueError("Dates must include a timezone")
        if self.status == "superseded":
            raise ValueError("Use correction to supersede an existing record")
        return self


class CaptureInput(MemoryInput):
    idempotency_key: str = Field(min_length=1, max_length=200)


class CorrectionInput(StrictModel):
    expected_revision: int = Field(ge=1)
    replacement: MemoryInput


class StatusInput(StrictModel):
    expected_revision: int = Field(ge=1)
    status: Literal["candidate", "active", "expired", "disputed"]


class LinkInput(StrictModel):
    target_id: UUID
    kind: Literal["derived_from", "relates_to", "contradicts"]


class CredentialInput(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    project_ids: list[UUID] = Field(default_factory=list, max_length=100)
    allow_shared: bool = False
    can_write: bool = False
    all_projects: bool = False


class CheckpointInput(StrictModel):
    project_id: UUID
    session_id: str = Field(min_length=1, max_length=200)
    task_ref: str | None = Field(default=None, max_length=1000)
    objective: str = Field(min_length=1, max_length=3000)
    completed: list[str] = Field(default_factory=list, max_length=50)
    verification: list[str] = Field(default_factory=list, max_length=50)
    pending: list[str] = Field(default_factory=list, max_length=50)
    next_action: str = Field(min_length=1, max_length=3000)
    memory_ids: list[UUID] = Field(default_factory=list, max_length=50)
    expected_revision: int = Field(default=0, ge=0)


class SearchInput(StrictModel):
    query: str = Field(min_length=1, max_length=2000)
    project_id: UUID | None = None
    cross_project: bool = False
    include_shared: bool = True
    types: list[MemoryType] = Field(default_factory=list)
    limit: int = Field(default=8, ge=1, le=50)
    include_inactive: bool = False


class ContextInput(SearchInput):
    task_ref: str | None = None
    max_chars: int = Field(default=12000, ge=1000, le=50000)


class ObservationInput(StrictModel):
    project_id: UUID
    text: str = Field(min_length=1, max_length=12000)
    source: Source
    idempotency_key: str = Field(min_length=1, max_length=200)
