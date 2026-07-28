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
            packet_id=str(uuid.uuid4()),
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
# Evidence packet store
# ---------------------------------------------------------------------------

class EvidencePacketStore:
    """Ephemeral store for approved evidence preview packets.

    Packets are stored in-process only and keyed by their server-assigned
    ``packet_id``.  The caller references a packet in the generation request
    via ``evidence_packet_id`` to avoid resending all evidence items.
    """

    def __init__(self) -> None:
        self._packets: dict[str, EvidencePreviewPacket] = {}

    def save(self, packet: EvidencePreviewPacket) -> None:
        self._packets[packet.packet_id] = packet

    def get(self, packet_id: str) -> EvidencePreviewPacket | None:
        return self._packets.get(packet_id)


# ---------------------------------------------------------------------------
# Article generation service
# ---------------------------------------------------------------------------

# Priority-ordered field names used when scanning evidence items for each
# content category.
_CITATION_FIELDS = ("citation", "reference", "source_ref", "bib_ref")
_OVERVIEW_FIELDS = ("context", "overview_text", "background", "intro", "overview")
_SUMMARY_FIELDS = ("summary", "abstract", "description", "text", "content")
_APPROACH_FIELDS = ("approach", "method", "strategy", "technique", "conservation_approach")
_GAP_FIELDS = ("knowledge_gap", "gap", "research_gap")
_ACTION_FIELDS = ("action_recommendations", "recommendations", "action", "grower_action")
_FINDING_FIELDS = ("finding", "result", "conclusion", "outcome", "synthesis")


def _first_str(item: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    """Return the first non-empty string value found in *fields*."""
    for f in fields:
        val = item.get(f)
        if val:
            return str(val)
    return None


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

    def generate(
        self,
        request: ArticleGenerationRequest,
        evidence_items: list[dict[str, Any]] | None = None,
        verified_projects_override: list[VerifiedProject] | None = None,
    ) -> ArticleGenerationResponse:
        """Generate an article from *request* plus resolved evidence.

        Parameters
        ----------
        request:
            The generation contract supplied by the caller.
        evidence_items:
            Resolved evidence items (from a packet store lookup or from
            ``request.evidence_items``).  Callers should pass this explicitly
            after resolving any ``evidence_packet_id``.  Falls back to
            ``request.evidence_items`` when ``None``.
        verified_projects_override:
            Verified-project rows already extracted during the preview step.
            When provided, these are merged with any rows re-extracted from
            *evidence_items* (deduplication applied).
        """
        if evidence_items is None:
            evidence_items = list(request.evidence_items)

        article_id = str(uuid.uuid4())
        mode = request.generation_mode.mode
        unavailable = list(request.generation_mode.unavailable_dependencies)
        warnings: list[str] = []

        # Extract verified projects from evidence, then merge any override rows
        verified_projects = EvidencePreviewService._extract_verified_projects(evidence_items)
        if verified_projects_override:
            existing_keys = {
                (p.project_name, p.country, p.region) for p in verified_projects
            }
            for proj in verified_projects_override:
                key = (proj.project_name, proj.country, proj.region)
                if key not in existing_keys:
                    verified_projects.append(proj)
                    existing_keys.add(key)

        # Full-Continuum mode is only valid when evidence was actually consumed.
        # Issue a warning if no evidence was supplied.
        if mode == "full_continuum" and not evidence_items:
            warnings.append(
                "Full-Continuum mode was declared but no evidence was supplied. "
                "No corpus evidence was consumed by this generation."
            )

        if mode == "limited_evidence":
            warnings.append(
                "Article generated in limited-evidence mode. "
                "Some Continuum dependencies are unavailable: "
                + (", ".join(unavailable) if unavailable else "none listed")
                + ". Content is restricted to evidence explicitly supplied "
                "in the brief and operator notes."
            )

        sections = self._build_sections(
            request, mode, warnings, evidence_items, verified_projects
        )

        body_text = " ".join(s.body for s in sections)
        word_count = len(body_text.split())

        # Determine whether evidence was sufficient to meet the word-count floor
        insufficient = word_count < request.brief.target_word_count_min
        if insufficient:
            warnings.append(
                f"Insufficient evidence: generated {word_count} words but the "
                f"requested minimum is {request.brief.target_word_count_min}. "
                "Provide richer evidence items to meet the target word count."
            )

        return ArticleGenerationResponse(
            article_id=article_id,
            title=request.brief.title,
            mode=mode,  # type: ignore[arg-type]
            word_count=word_count,
            sections=sections,
            verified_projects=verified_projects,
            unavailable_dependencies=unavailable,
            warnings=warnings,
            insufficient_evidence=insufficient,
        )

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_sections(
        self,
        request: ArticleGenerationRequest,
        mode: str,
        warnings: list[str],
        evidence_items: list[dict[str, Any]],
        verified_projects: list[VerifiedProject],
    ) -> list[GeneratedSection]:
        """Assemble the full FCOS article structure from supplied evidence.

        Sections that lack supporting evidence are explicitly labelled
        rather than silently omitted or filled with fabricated content.
        """
        brief = request.brief
        notes = request.operator_notes or ""
        sections: list[GeneratedSection] = []

        # Collect evidence data by category
        citations: list[str] = []
        overview_texts: list[str] = []
        approaches: list[str] = []
        # (name, body, citation_str|None) — citation_str from evidence `citation` field only
        spotlights: list[tuple[str, str, str | None]] = []
        knowledge_gaps: list[str] = []
        grower_actions: list[str] = []
        synthesis_findings: list[str] = []

        for item in evidence_items:
            if c := _first_str(item, _CITATION_FIELDS):
                citations.append(c)
            if o := _first_str(item, _OVERVIEW_FIELDS):
                overview_texts.append(o)
            if s := _first_str(item, _SUMMARY_FIELDS):
                name = str(item.get("project_name") or item.get("project") or "")
                # Use the bibliographic citation from the item, not the source_id
                item_cite = _first_str(item, _CITATION_FIELDS)
                spotlights.append((name, s, item_cite))
            if a := _first_str(item, _APPROACH_FIELDS):
                if a not in approaches:
                    approaches.append(a)
            if g := _first_str(item, _GAP_FIELDS):
                knowledge_gaps.append(g)
            if ac := _first_str(item, _ACTION_FIELDS):
                grower_actions.append(ac)
            if f := _first_str(item, _FINDING_FIELDS):
                synthesis_findings.append(f)

        # ----------------------------------------------------------------
        # 1. Introduction
        # ----------------------------------------------------------------
        intro_parts = [brief.focus]
        if notes.strip():
            intro_parts.append(notes.strip())
        if brief.scope_hints:
            intro_parts.append(
                "Thematic scope: " + "; ".join(brief.scope_hints) + "."
            )
        sections.append(
            GeneratedSection(
                heading="Introduction",
                body=" ".join(intro_parts),
                citations=[],
            )
        )

        # ----------------------------------------------------------------
        # 2. Orchid Conservation Overview
        # ----------------------------------------------------------------
        if overview_texts:
            overview_body = " ".join(overview_texts)
            sections.append(
                GeneratedSection(
                    heading="Orchid Conservation Overview",
                    body=overview_body,
                    citations=citations[:2],
                )
            )
        else:
            sections.append(
                GeneratedSection(
                    heading="Orchid Conservation Overview",
                    body="No overview or background evidence was supplied in the evidence packet.",
                    citations=[],
                )
            )

        # ----------------------------------------------------------------
        # 3. Verified Projects
        # ----------------------------------------------------------------
        if verified_projects:
            proj_list = "; ".join(
                f"{p.project_name}"
                + (
                    f" ({p.country}"
                    + (f", {p.region})" if p.region else ")")
                    if p.country
                    else ""
                )
                for p in verified_projects
            )
            proj_body = (
                f"The following {len(verified_projects)} project"
                f"{'s' if len(verified_projects) != 1 else ''} "
                f"{'are' if len(verified_projects) != 1 else 'is'} "
                f"supported by verified evidence: {proj_list}. "
                "No additional projects have been inferred or fabricated."
            )
            sections.append(
                GeneratedSection(
                    heading="Verified Projects",
                    body=proj_body,
                    citations=[],
                )
            )
        else:
            sections.append(
                GeneratedSection(
                    heading="Verified Projects",
                    body=(
                        "No verified projects were identified in the supplied evidence. "
                        "Project counts and names are not fabricated."
                    ),
                    citations=[],
                )
            )

        # ----------------------------------------------------------------
        # 4. Conservation Approaches
        # ----------------------------------------------------------------
        if approaches:
            approach_body = (
                "Evidence documents the following conservation approaches: "
                + "; ".join(approaches) + "."
            )
            sections.append(
                GeneratedSection(
                    heading="Conservation Approaches",
                    body=approach_body,
                    citations=citations[:2],
                )
            )
        else:
            sections.append(
                GeneratedSection(
                    heading="Conservation Approaches",
                    body="No approach data was supplied in the evidence packet.",
                    citations=[],
                )
            )

        # ----------------------------------------------------------------
        # 5. Project Spotlights (up to 4, only when evidence has summaries)
        # ----------------------------------------------------------------
        for i, (name, body_text, cite_str) in enumerate(spotlights[:4]):
            heading = (
                f"Project Spotlight: {name}" if name else f"Evidence Spotlight {i + 1}"
            )
            cites = [cite_str] if cite_str else []
            sections.append(
                GeneratedSection(heading=heading, body=body_text, citations=cites)
            )

        # ----------------------------------------------------------------
        # 6. Evidence Synthesis
        # ----------------------------------------------------------------
        if synthesis_findings:
            synthesis_body = " ".join(synthesis_findings)
            sections.append(
                GeneratedSection(
                    heading="Evidence Synthesis",
                    body=synthesis_body,
                    citations=citations,
                )
            )
        else:
            sections.append(
                GeneratedSection(
                    heading="Evidence Synthesis",
                    body="No synthesis findings were supplied in the evidence packet.",
                    citations=[],
                )
            )

        # ----------------------------------------------------------------
        # 7. Knowledge Gaps
        # ----------------------------------------------------------------
        if knowledge_gaps:
            sections.append(
                GeneratedSection(
                    heading="Knowledge Gaps",
                    body=" ".join(knowledge_gaps),
                    citations=[],
                )
            )
        else:
            sections.append(
                GeneratedSection(
                    heading="Knowledge Gaps",
                    body="No knowledge gap data was supplied in the evidence packet.",
                    citations=[],
                )
            )

        # ----------------------------------------------------------------
        # 8. Grower Actions
        # ----------------------------------------------------------------
        if grower_actions:
            sections.append(
                GeneratedSection(
                    heading="Grower Actions",
                    body=" ".join(grower_actions),
                    citations=[],
                )
            )
        else:
            sections.append(
                GeneratedSection(
                    heading="Grower Actions",
                    body="No grower action recommendations were supplied in the evidence packet.",
                    citations=[],
                )
            )

        # ----------------------------------------------------------------
        # 9. Calyx Perspective
        # ----------------------------------------------------------------
        n_items = len(evidence_items)
        n_proj = len(verified_projects)
        if n_items > 0:
            calyx_body = (
                f"Based on {n_items} evidence item{'s' if n_items != 1 else ''} reviewed, "
                f"with {n_proj} verified project{'s' if n_proj != 1 else ''} identified, "
                "this Calyx report reflects only claims directly supported by the supplied "
                "evidence. No conservation status, project count, or citation has been "
                "asserted beyond what the evidence explicitly states."
            )
        else:
            calyx_body = (
                "No evidence was supplied for this report. "
                "The Calyx Perspective cannot be formed without verified data. "
                "Conservation status, project counts, and citations are not fabricated."
            )
        sections.append(
            GeneratedSection(heading="Calyx Perspective", body=calyx_body, citations=[])
        )

        # ----------------------------------------------------------------
        # 10. Sources / Endnotes
        # ----------------------------------------------------------------
        if citations:
            sources_body = "\n".join(
                f"{i + 1}. {c}" for i, c in enumerate(citations)
            )
            sections.append(
                GeneratedSection(heading="Sources", body=sources_body, citations=[])
            )

        # ----------------------------------------------------------------
        # 11. Evidence Availability
        # ----------------------------------------------------------------
        if mode == "full_continuum" and evidence_items:
            avail_body = (
                "This article was generated using evidence supplied from the "
                "Orchid Continuum corpus. All citations are drawn directly from "
                "the provided evidence items."
            )
        elif mode == "full_continuum":
            avail_body = (
                "Full-Continuum mode was declared but no evidence was supplied. "
                "No corpus evidence was consumed by this generation run."
            )
        else:
            unavail_deps = list(request.generation_mode.unavailable_dependencies)
            if unavail_deps:
                avail_body = (
                    "Article generated in limited-evidence mode. "
                    "The following Continuum dependencies were unavailable at generation "
                    "time: " + ", ".join(unavail_deps)
                    + ". Content is restricted to explicitly supplied evidence."
                )
            else:
                avail_body = (
                    "Article generated in limited-evidence mode. "
                    "No Continuum dependencies were reported as unavailable, "
                    "but full-Continuum mode was not selected."
                )
        sections.append(
            GeneratedSection(
                heading="Evidence Availability",
                body=avail_body,
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
