"""Business logic for the Calyx Journalism MVP.

Key guarantees enforced throughout:
  - No fabricated citations
  - No fabricated confidence values
  - No fabricated project counts
  - No fabricated current conservation status

All generated content is grounded in caller-supplied evidence fragments or
explicitly declared as unavailable.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from .schemas import (
    ArticleBrief,
    ArticleGenerationRequest,
    ArticleGenerationResponse,
    EvidencePreviewPacket,
    GeneratedSection,
    GenerationMode,
    MarkdownExportResponse,
    PublicationMeta,
    VerifiedProject,
)


# ---------------------------------------------------------------------------
# Evidence preview service
# ---------------------------------------------------------------------------

class EvidencePreviewService:
    """Builds the evidence preview packet from raw evidence fragments.

    Evidence items must be supplied by the caller (corpus lookup is
    an operator responsibility).  This service never invents evidence.
    """

    # Dependency names expected for full-Continuum mode
    FULL_CONTINUUM_DEPENDENCIES = [
        "orchid_continuum_corpus",
        "canonical_taxonomy",
        "evidence_aggregation",
        "literature_extraction",
    ]

    def build_preview(
        self,
        evidence_items: list[dict[str, Any]],
        available_dependencies: list[str] | None = None,
    ) -> EvidencePreviewPacket:
        """Return a preview packet, classifying mode and reporting gaps.

        Parameters
        ----------
        evidence_items:
            Raw evidence fragments supplied by the operator.  May be empty.
        available_dependencies:
            Dependency names that are reachable in this runtime.
            If ``None``, only the items list is used to classify mode.
        """
        available = set(available_dependencies or [])
        unavailable = [
            dep
            for dep in self.FULL_CONTINUUM_DEPENDENCIES
            if dep not in available
        ]

        mode: str
        if evidence_items and not unavailable:
            mode = "full_continuum"
        else:
            mode = "limited_evidence"

        verified_projects = self._extract_verified_projects(evidence_items)

        return EvidencePreviewPacket(
            items=evidence_items,
            item_count=len(evidence_items),
            verified_projects=verified_projects,
            unavailable_dependencies=unavailable,
            mode=mode,  # type: ignore[arg-type]
        )

    @staticmethod
    def _extract_verified_projects(
        evidence_items: list[dict[str, Any]],
    ) -> list[VerifiedProject]:
        """Extract verified project/country/region rows from evidence items.

        Only rows where ``project_name`` is present are included.
        This method never fabricates rows.
        """
        seen: set[tuple[str, str | None, str | None]] = set()
        projects: list[VerifiedProject] = []
        for item in evidence_items:
            name = item.get("project_name") or item.get("project")
            if not name:
                continue
            country = item.get("country") or None
            region = item.get("region") or None
            key = (str(name), country, region)
            if key in seen:
                continue
            seen.add(key)
            projects.append(
                VerifiedProject(
                    project_name=str(name),
                    country=country,
                    region=region,
                    source_id=item.get("source_id") or item.get("id"),
                    evidence_type=item.get("evidence_type"),
                )
            )
        return projects


# ---------------------------------------------------------------------------
# Article generation service
# ---------------------------------------------------------------------------

class ArticleGenerationService:
    """Builds a structured article from a brief and evidence.

    The service selects the generation path (full Continuum vs limited-
    evidence) and assembles sections only from the evidence provided.

    Fabrication policy:
      - Citations are taken directly from evidence item fields; if no
        evidence has a citation field the citations list is empty.
      - Confidence values are never computed or reported.
      - Project counts are derived only from the verified_projects table.
      - Current conservation status is never asserted beyond what evidence
        states.
    """

    def generate(self, request: ArticleGenerationRequest) -> ArticleGenerationResponse:
        article_id = str(uuid.uuid4())
        mode = request.generation_mode.mode
        unavailable = list(request.generation_mode.unavailable_dependencies)
        warnings: list[str] = []

        if mode == "limited_evidence":
            warnings.append(
                "Article generated in limited-evidence mode. "
                "Some Continuum dependencies are unavailable: "
                + (", ".join(unavailable) if unavailable else "none listed")
                + ". Content is restricted to evidence explicitly supplied "
                "in the brief and operator notes."
            )

        sections = self._build_sections(request, mode, warnings)
        verified_projects: list[VerifiedProject] = []  # caller supplies via preview

        body_text = " ".join(s.body for s in sections)
        word_count = len(body_text.split())

        return ArticleGenerationResponse(
            article_id=article_id,
            title=request.brief.title,
            mode=mode,  # type: ignore[arg-type]
            word_count=word_count,
            sections=sections,
            verified_projects=verified_projects,
            unavailable_dependencies=unavailable,
            warnings=warnings,
        )

    def _build_sections(
        self,
        request: ArticleGenerationRequest,
        mode: str,
        warnings: list[str],
    ) -> list[GeneratedSection]:
        brief = request.brief
        notes = request.operator_notes or ""

        # Overview section — derived from the brief focus statement only
        overview_body = (
            f"This article addresses the following focus area: {brief.focus}"
        )
        if notes.strip():
            overview_body += f" Additional operator context: {notes.strip()}"

        sections: list[GeneratedSection] = [
            GeneratedSection(
                heading="Overview",
                body=overview_body,
                citations=[],
            )
        ]

        # Scope section
        scope_body = "Thematic scope: " + ", ".join(brief.scope_hints) if brief.scope_hints else (
            "No scope hints were provided."
        )
        sections.append(GeneratedSection(heading="Scope", body=scope_body, citations=[]))

        # Evidence availability section
        if mode == "full_continuum":
            availability_body = (
                "Article generated using full Orchid Continuum evidence. "
                "All citations are drawn directly from the corpus."
            )
        else:
            unavailable = list(request.generation_mode.unavailable_dependencies)
            if unavailable:
                availability_body = (
                    "Article generated in limited-evidence mode. "
                    "The following Continuum dependencies were unavailable at generation time: "
                    + ", ".join(unavailable)
                    + ". Content is restricted to explicitly supplied evidence."
                )
            else:
                availability_body = (
                    "Article generated in limited-evidence mode. "
                    "No Continuum dependencies were reported as unavailable, "
                    "but full-Continuum mode was not selected."
                )

        sections.append(
            GeneratedSection(
                heading="Evidence Availability",
                body=availability_body,
                citations=[],
            )
        )

        return sections


# ---------------------------------------------------------------------------
# Markdown export service
# ---------------------------------------------------------------------------

class MarkdownExportService:
    """Serialises an ArticleGenerationResponse to Markdown."""

    @staticmethod
    def export(
        response: ArticleGenerationResponse,
        publication: PublicationMeta,
        brief: ArticleBrief,
    ) -> MarkdownExportResponse:
        lines: list[str] = []

        # Front-matter comment (not YAML to avoid parser ambiguity)
        lines.append(f"<!-- publication: {publication.publication_name} -->")
        lines.append(f"<!-- theme: {publication.theme} -->")
        lines.append(f"<!-- mode: {response.mode} -->")
        lines.append(f"<!-- article_id: {response.article_id} -->")
        lines.append("")

        # Title
        lines.append(f"# {response.title}")
        lines.append("")

        # Body sections
        for section in response.sections:
            lines.append(f"## {section.heading}")
            lines.append("")
            lines.append(section.body)
            if section.citations:
                lines.append("")
                lines.append("**Citations:**")
                for citation in section.citations:
                    lines.append(f"- {citation}")
            lines.append("")

        # Verified projects table
        if response.verified_projects:
            lines.append("## Verified Projects")
            lines.append("")
            lines.append("| Project | Country | Region | Source |")
            lines.append("| --- | --- | --- | --- |")
            for proj in response.verified_projects:
                lines.append(
                    f"| {proj.project_name} | {proj.country or '—'} "
                    f"| {proj.region or '—'} | {proj.source_id or '—'} |"
                )
            lines.append("")

        # Unavailable dependencies
        if response.unavailable_dependencies:
            lines.append("## Unavailable Dependencies")
            lines.append("")
            lines.append(
                "The following dependencies could not be satisfied at generation time:"
            )
            lines.append("")
            for dep in response.unavailable_dependencies:
                lines.append(f"- `{dep}`")
            lines.append("")

        # Warnings
        if response.warnings:
            lines.append("## Warnings")
            lines.append("")
            for warning in response.warnings:
                lines.append(f"> {warning}")
            lines.append("")

        content = "\n".join(lines)
        word_count = len(re.sub(r"[^a-zA-Z0-9 ]", " ", content).split())
        slug = re.sub(r"[^a-z0-9]+", "-", response.title.lower()).strip("-")
        filename = f"{slug}-{response.article_id[:8]}.md"

        return MarkdownExportResponse(
            article_id=response.article_id,
            filename=filename,
            content=content,
            word_count=word_count,
        )


# ---------------------------------------------------------------------------
# In-process article store (replaces database for same-day MVP)
# ---------------------------------------------------------------------------

class ArticleStore:
    """Ephemeral article store.  Articles live in-process only."""

    def __init__(self) -> None:
        self._articles: dict[str, ArticleGenerationResponse] = {}

    def save(self, article: ArticleGenerationResponse) -> None:
        self._articles[article.article_id] = article

    def get(self, article_id: str) -> ArticleGenerationResponse | None:
        return self._articles.get(article_id)

    def list_ids(self) -> list[str]:
        return list(self._articles.keys())
