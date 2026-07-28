"""Pydantic schemas for the Calyx Journalism MVP.

All schemas enforce strict no-fabrication conventions:
  - no fabricated citations
  - no fabricated confidence values
  - no fabricated project counts or current status
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Publication metadata
# ---------------------------------------------------------------------------

class PublicationMeta(BaseModel):
    """Identifies the target publication and its thematic scope."""

    publication_id: str = Field(min_length=1, max_length=200)
    publication_name: str = Field(min_length=1, max_length=500)
    theme: str = Field(min_length=1, max_length=200)
    description: str | None = None
    # ISO 639-1 language code for the output article
    language: str = Field(default="en", max_length=10)


# ---------------------------------------------------------------------------
# Article brief
# ---------------------------------------------------------------------------

class ArticleBrief(BaseModel):
    """Operator-supplied article brief submitted before evidence preview."""

    title: str = Field(min_length=1, max_length=500)
    focus: str = Field(
        min_length=1,
        max_length=2000,
        description="Thematic focus statement (what the article should cover).",
    )
    target_word_count_min: int = Field(default=800, ge=100, le=50_000)
    target_word_count_max: int = Field(default=1500, ge=100, le=50_000)
    # Taxonomy or geographic scope hints (optional free-text)
    scope_hints: list[str] = Field(default_factory=list)
    # Operator-provided tags for search / categorisation
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def word_count_order(self) -> "ArticleBrief":
        if self.target_word_count_min > self.target_word_count_max:
            raise ValueError("target_word_count_min must be ≤ target_word_count_max")
        return self


# ---------------------------------------------------------------------------
# Evidence preview packet
# ---------------------------------------------------------------------------

class VerifiedProject(BaseModel):
    """A single project/country/region row drawn from verified evidence."""

    project_name: str
    country: str | None = None
    region: str | None = None
    # Evidence origin — never inferred, only passed through from corpus
    source_id: str | None = None
    evidence_type: str | None = None


class EvidencePreviewPacket(BaseModel):
    """Read-only preview of the evidence that will inform article generation.

    Calyx never fabricates citations, confidence scores, project counts, or
    current status.  All fields are derived directly from the corpus.
    """

    # Server-assigned packet ID — use this in ArticleGenerationRequest to
    # reference this packet without re-sending all items.
    packet_id: str = ""
    # Evidence items — each item is a raw corpus fragment
    items: list[dict[str, Any]] = Field(default_factory=list)
    item_count: int = 0
    # Verified project/country/region table (only populated when evidence exists)
    verified_projects: list[VerifiedProject] = Field(default_factory=list)
    # Dependencies that could not be satisfied — explicit, never hidden
    unavailable_dependencies: list[str] = Field(default_factory=list)
    mode: Literal["full_continuum", "limited_evidence"] = "limited_evidence"

    @model_validator(mode="after")
    def sync_item_count(self) -> "EvidencePreviewPacket":
        self.item_count = len(self.items)
        return self


# ---------------------------------------------------------------------------
# Article generation contract
# ---------------------------------------------------------------------------

class GenerationMode(BaseModel):
    """Explicit full-Continuum vs limited-evidence mode declaration."""

    mode: Literal["full_continuum", "limited_evidence"]
    reason: str | None = None
    # Dependencies that are unavailable — operator must acknowledge these
    unavailable_dependencies: list[str] = Field(default_factory=list)


class ArticleGenerationRequest(BaseModel):
    """Complete contract sent to trigger article generation."""

    publication: PublicationMeta
    brief: ArticleBrief
    generation_mode: GenerationMode
    # Optional operator notes that may guide generation without fabrication
    operator_notes: str | None = Field(default=None, max_length=5000)
    # Approved evidence from the preview step.
    # Provide EITHER evidence_packet_id (server-side lookup) OR evidence_items
    # directly.  If both are given, the packet-store lookup takes precedence.
    evidence_packet_id: str | None = Field(default=None)
    # Inline evidence items (used when no packet_id is available)
    evidence_items: list[dict[str, Any]] = Field(default_factory=list)


class GeneratedSection(BaseModel):
    """A single section of the generated article."""

    heading: str
    body: str
    # Citations drawn only from provided evidence — list is empty when evidence
    # is unavailable; never contains fabricated references
    citations: list[str] = Field(default_factory=list)


class ArticleGenerationResponse(BaseModel):
    """Structured article generation response.

    Calyx guarantees:
      - no fabricated citations
      - no fabricated confidence values
      - no fabricated project counts
      - no fabricated current status
    Only content that can be grounded in the provided evidence is included.
    """

    article_id: str
    title: str
    mode: Literal["full_continuum", "limited_evidence"]
    word_count: int
    sections: list[GeneratedSection]
    # Verified projects table (empty when no evidence available)
    verified_projects: list[VerifiedProject]
    # Explicit unavailable dependencies — never hidden
    unavailable_dependencies: list[str]
    # Generation warnings (e.g. evidence was sparse)
    warnings: list[str]
    # True when evidence was insufficient to meet the requested word-count floor
    insufficient_evidence: bool = False


# ---------------------------------------------------------------------------
# Markdown export
# ---------------------------------------------------------------------------

class MarkdownExportRequest(BaseModel):
    article_id: str = Field(min_length=1)


class MarkdownExportResponse(BaseModel):
    article_id: str
    filename: str
    content: str
    word_count: int
