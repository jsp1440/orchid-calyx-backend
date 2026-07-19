from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Scientific Intelligence": ("scientific", "taxonomy", "trait", "habitat", "climate", "species", "genus"),
    "Educational Intelligence": ("education", "learning", "learner", "curriculum", "teaching"),
    "Research Intelligence": ("research", "evidence", "source", "literature", "study"),
    "Engineering Intelligence": ("backend", "frontend", "api", "repository", "service", "fastapi", "runtime"),
    "Knowledge Graph": ("knowledge graph", "oc_graph", "graph", "node", "edge"),
    "Runtime": ("runtime", "worker", "queue", "scheduler", "executor", "autonomous"),
    "Vision": ("vision", "mission", "charter", "north star"),
    "Collection Management": ("collection", "accession", "plant", "show", "judging"),
    "Conservation": ("conservation", "stewardship", "habitat", "threat", "protect"),
    "Historical Intelligence": ("history", "historical", "culture", "institutional memory"),
    "Reasoning": ("reasoning", "inference", "resolution", "ontology", "confidence"),
    "Community": ("community", "citizen", "volunteer", "grower", "observer"),
    "Governance": ("governance", "constitution", "approval", "audit", "policy", "authority"),
    "Infrastructure": ("database", "postgres", "deployment", "render", "migration", "github actions"),
    "Planning": ("roadmap", "planning", "future build", "gap", "blocker"),
}

COMPONENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "backend": ("backend", "fastapi", "api", "app/main.py"),
    "frontend": ("frontend", "control panel", "mission control", "ui"),
    "runtime": ("runtime", "worker", "scheduler", "executor", "queue"),
    "knowledge_graph": ("knowledge graph", "oc_graph", "graph"),
    "taxonomy": ("taxonomy", "oc_taxonomy", "taxon"),
    "ontology": ("ontology", "resolution", "registry", "evidence"),
    "publication": ("publication", "publish", "dry-run"),
    "missions": ("mission", "queue", "orchestration"),
    "database": ("database", "postgres", "sql", "migration"),
    "brain": ("brain", "architecture", "reasoning"),
}

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "shall",
    "should",
    "must",
    "build",
    "orchid",
    "continuum",
}


@dataclass(frozen=True)
class Provenance:
    document_id: str
    path: str
    section: str
    line: int
    excerpt: str


@dataclass
class DocumentRecord:
    document_id: str
    path: str
    title: str
    purpose: str
    checksum: str
    sections: list[str]
    concepts: list[str]
    domains: list[str]
    components: list[str]
    repositories: list[str]
    services: list[str]
    apis: list[str]
    workflows: list[str]
    datasets: list[str]
    ontologies: list[str]
    educational_concepts: list[str]
    scientific_concepts: list[str]
    conservation_concepts: list[str]
    ai_agents: list[str]
    future_work: list[str]
    dependencies: list[str]
    provenance: list[Provenance] = field(default_factory=list)


@dataclass
class OntologyDomain:
    name: str
    purpose: str
    responsibilities: list[str]
    inputs: list[str]
    outputs: list[str]
    dependencies: list[str]
    current_maturity: str
    future_work: list[str]
    provenance: list[Provenance]


@dataclass
class ArchitectureBuildResult:
    documents: list[DocumentRecord]
    ontology: list[OntologyDomain]
    canonical_terms: dict[str, list[str]]
    conflicts: list[dict[str, object]]
    dependencies: list[dict[str, object]]
    gaps: list[dict[str, object]]
    roadmap: list[dict[str, object]]


class BrainArchitect:
    """Deterministic architecture synthesis pipeline for repository documents."""

    document_extensions = {".md", ".txt"}

    def __init__(self, repo_root: Path, output_dir: Path | None = None):
        self.repo_root = repo_root.resolve()
        self.output_dir = output_dir or self.repo_root / "docs" / "architecture" / "BUILD-080"

    def run(self, write: bool = True) -> ArchitectureBuildResult:
        documents = self.ingest_documents()
        canonical_terms, conflicts = self.normalize_concepts(documents)
        ontology = self.build_ontology(documents)
        dependencies = self.build_dependency_graph(documents)
        gaps = self.build_gap_analysis(documents, ontology)
        roadmap = self.build_roadmap(gaps, ontology)
        result = ArchitectureBuildResult(
            documents=documents,
            ontology=ontology,
            canonical_terms=canonical_terms,
            conflicts=conflicts,
            dependencies=dependencies,
            gaps=gaps,
            roadmap=roadmap,
        )
        if write:
            self.write_outputs(result)
        return result

    def ingest_documents(self) -> list[DocumentRecord]:
        records: list[DocumentRecord] = []
        for path in self._document_paths():
            text = path.read_text(encoding="utf-8", errors="replace")
            relative = path.relative_to(self.repo_root).as_posix()
            lines = text.splitlines()
            sections = self._sections(lines)
            title = self._title(path, lines)
            doc_id = self._document_id(relative)
            concepts = self._extract_concepts(text)
            domains = self._match_keywords(text, DOMAIN_KEYWORDS)
            components = self._match_keywords(text, COMPONENT_KEYWORDS)
            provenance = self._provenance(doc_id, relative, lines)
            records.append(
                DocumentRecord(
                    document_id=doc_id,
                    path=relative,
                    title=title,
                    purpose=self._purpose(lines, title),
                    checksum=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    sections=sections,
                    concepts=concepts,
                    domains=domains,
                    components=components,
                    repositories=self._extract_repositories(text),
                    services=self._extract_services(text),
                    apis=sorted(set(re.findall(r"/api/[A-Za-z0-9_./{}-]+", text))),
                    workflows=self._sentences_matching(text, ("workflow", "lifecycle", "process", "pipeline")),
                    datasets=self._sentences_matching(text, ("dataset", "source", "evidence", "reference")),
                    ontologies=self._sentences_matching(text, ("ontology", "registry", "term", "synonym")),
                    educational_concepts=self._sentences_matching(text, DOMAIN_KEYWORDS["Educational Intelligence"]),
                    scientific_concepts=self._sentences_matching(text, DOMAIN_KEYWORDS["Scientific Intelligence"]),
                    conservation_concepts=self._sentences_matching(text, DOMAIN_KEYWORDS["Conservation"]),
                    ai_agents=self._sentences_matching(text, ("agent", "architect", "orchestrator", "intelligence")),
                    future_work=self._sentences_matching(text, ("future", "roadmap", "todo", "blocker", "gap")),
                    dependencies=self._extract_dependencies(text, components),
                    provenance=provenance,
                )
            )
        return sorted(records, key=lambda record: record.path)

    def normalize_concepts(self, documents: Iterable[DocumentRecord]) -> tuple[dict[str, list[str]], list[dict[str, object]]]:
        aliases: dict[str, set[str]] = {}
        conflicts: list[dict[str, object]] = []
        known_aliases = {
            "knowledge graph": {"knowledge graph", "kg", "oc graph", "oc_graph"},
            "runtime": {"runtime", "autonomous runtime", "runner", "worker"},
            "mission queue": {"mission queue", "controlled mission queue", "orchestration queue"},
            "ontology registry": {"ontology", "ontology registry", "resolution registry"},
            "canonical taxonomy": {"taxonomy", "canonical taxonomy", "oc_taxonomy"},
        }
        for canonical, values in known_aliases.items():
            aliases.setdefault(canonical, set()).update(values)

        for document in documents:
            for concept in document.concepts + document.components + document.domains:
                canonical = self._canonical_term(concept)
                aliases.setdefault(canonical, set()).add(concept)
            lowered = " ".join(document.future_work).lower()
            if "deprecated" in lowered or "superseded" in lowered:
                conflicts.append(
                    {
                        "type": "superseded_or_deprecated_reference",
                        "document_id": document.document_id,
                        "path": document.path,
                        "evidence": document.future_work[:3],
                    }
                )
            if "conflict" in lowered or "duplicate" in lowered:
                conflicts.append(
                    {
                        "type": "possible_duplicate_or_conflict",
                        "document_id": document.document_id,
                        "path": document.path,
                        "evidence": document.future_work[:3],
                    }
                )
        return {key: sorted(values) for key, values in sorted(aliases.items())}, conflicts

    def build_ontology(self, documents: list[DocumentRecord]) -> list[OntologyDomain]:
        domains: list[OntologyDomain] = []
        for domain in DOMAIN_KEYWORDS:
            matched = [doc for doc in documents if domain in doc.domains]
            provenance = [item for doc in matched[:5] for item in doc.provenance[:2]]
            components = sorted({component for doc in matched for component in doc.components})
            future_work = self._top_items([item for doc in matched for item in doc.future_work], 6)
            maturity = self._maturity(domain, matched)
            domains.append(
                OntologyDomain(
                    name=domain,
                    purpose=self._domain_purpose(domain, matched),
                    responsibilities=self._domain_responsibilities(domain, components),
                    inputs=self._domain_inputs(domain, matched),
                    outputs=self._domain_outputs(domain, matched),
                    dependencies=self._domain_dependencies(domain, matched),
                    current_maturity=maturity,
                    future_work=future_work or ["Keep provenance-linked architectural intent current as the system evolves."],
                    provenance=provenance,
                )
            )
        return domains

    def build_dependency_graph(self, documents: list[DocumentRecord]) -> list[dict[str, object]]:
        edges: set[tuple[str, str, str]] = set()
        for document in documents:
            components = document.components
            for source in components:
                for target in components:
                    if source != target:
                        edges.add((source, target, document.document_id))
            if "publication" in components and "ontology" in components:
                edges.add(("publication", "ontology", document.document_id))
            if "missions" in components and "runtime" in components:
                edges.add(("runtime", "missions", document.document_id))
            if "ontology" in components and "database" in components:
                edges.add(("ontology", "database", document.document_id))
        return [
            {"source": source, "target": target, "provenance_document_id": doc_id}
            for source, target, doc_id in sorted(edges)
        ]

    def build_gap_analysis(self, documents: list[DocumentRecord], ontology: list[OntologyDomain]) -> list[dict[str, object]]:
        paths = {doc.path for doc in documents}
        gaps: list[dict[str, object]] = []
        for domain in ontology:
            domain_docs = [doc for doc in documents if domain.name in doc.domains]
            if len(domain_docs) < 2:
                gaps.append(
                    {
                        "area": domain.name,
                        "priority": "high" if domain.name in {"Planning", "Reasoning"} else "medium",
                        "gap": "Architectural coverage is thin or indirect.",
                        "evidence": [doc.path for doc in domain_docs],
                    }
                )
            if not any(doc.apis or doc.services for doc in domain_docs) and domain.name in {
                "Educational Intelligence",
                "Historical Intelligence",
                "Collection Management",
                "Conservation",
            }:
                gaps.append(
                    {
                        "area": domain.name,
                        "priority": "medium",
                        "gap": "Executable service or API contract is not explicit in the source corpus.",
                        "evidence": [doc.path for doc in domain_docs[:5]],
                    }
                )
            if not any(doc.future_work for doc in domain_docs):
                gaps.append(
                    {
                        "area": domain.name,
                        "priority": "low",
                        "gap": "Future work is not explicitly captured.",
                        "evidence": [doc.path for doc in domain_docs[:3]],
                    }
                )
            if not any(doc.provenance for doc in domain_docs):
                gaps.append(
                    {
                        "area": domain.name,
                        "priority": "high",
                        "gap": "No statement-level provenance was extracted.",
                        "evidence": [doc.path for doc in domain_docs[:3]],
                    }
                )
        if not any(path.startswith("brain/") for path in paths):
            gaps.append({"area": "Brain", "priority": "high", "gap": "No Brain source documents were available.", "evidence": []})
        return gaps

    def build_roadmap(self, gaps: list[dict[str, object]], ontology: list[OntologyDomain] | None = None) -> list[dict[str, object]]:
        priority_order = {"high": 0, "medium": 1, "low": 2}
        roadmap = []
        for index, gap in enumerate(sorted(gaps, key=lambda item: (priority_order.get(str(item["priority"]), 9), str(item["area"]))), 1):
            roadmap.append(
                {
                    "build": f"BUILD-080.{index:02d}",
                    "purpose": f"Close architecture gap: {gap['gap']}",
                    "dependencies": [gap["area"]],
                    "estimated_complexity": "medium" if gap["priority"] == "high" else "low",
                    "architectural_impact": gap["priority"],
                    "recommended_sequence": index,
                    "blockers": gap.get("evidence") or ["Requires source documents or owner decision."],
                    "expected_deliverables": [f"{gap['area']} architecture note", "provenance-linked validation"],
                }
            )
        if roadmap or ontology is None:
            return roadmap
        priority_domains = [
            "Planning",
            "Reasoning",
            "Educational Intelligence",
            "Research Intelligence",
            "Conservation",
        ]
        domain_lookup = {domain.name: domain for domain in ontology}
        roadmap_purposes = {
            "Planning": "Convert Brain Architect output into owner-sequenced future build briefs.",
            "Reasoning": "Define the next reasoning architecture layer across ontology resolution, evidence, and readiness decisions.",
            "Educational Intelligence": "Specify education modules that use the knowledge graph without hiding provenance or uncertainty.",
            "Research Intelligence": "Harden research-source intake, evidence review, and architecture-level source governance.",
            "Conservation": "Map conservation intelligence responsibilities, datasets, and stewardship workflows into implementation-ready plans.",
        }
        for index, name in enumerate(priority_domains, 1):
            domain = domain_lookup[name]
            roadmap.append(
                {
                    "build": f"BUILD-080.R{index:02d}",
                    "purpose": roadmap_purposes[name],
                    "dependencies": domain.dependencies[:3],
                    "estimated_complexity": "medium",
                    "architectural_impact": "medium",
                    "recommended_sequence": index,
                    "blockers": ["Owner sequencing decision"],
                    "expected_deliverables": [f"{name} implementation brief", "updated provenance index"],
                }
            )
        return roadmap

    def write_outputs(self, result: ArchitectureBuildResult) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._write_json("architecture_inventory.json", [self._record_json(doc) for doc in result.documents])
        self._write_json("architecture_ontology.json", [self._domain_json(domain) for domain in result.ontology])
        self._write_json("canonical_terms.json", result.canonical_terms)
        self._write_json("provenance_index.json", self._provenance_index(result.documents))
        self._write_json("gap_analysis.json", result.gaps)
        self._write_json("roadmap.json", result.roadmap)
        self._write_markdown("Architecture_Summary.md", self._summary_markdown(result))
        self._write_markdown("Orchid_Continuum_Master_Architecture.md", self._master_markdown(result))
        self._write_markdown("dependency_graph.md", self._dependency_markdown(result))
        self._write_markdown("gap_analysis.md", self._gap_markdown(result))
        self._write_markdown("roadmap.md", self._roadmap_markdown(result))

    def _document_paths(self) -> list[Path]:
        candidates: list[Path] = []
        for root_name in ("brain", "docs"):
            root = self.repo_root / root_name
            if root.exists():
                candidates.extend(
                    path
                    for path in root.rglob("*")
                    if path.suffix.lower() in self.document_extensions and not self._is_generated_output(path)
                )
        for path in (self.repo_root / "README.md",):
            if path.exists():
                candidates.append(path)
        return sorted(set(candidates))

    def _is_generated_output(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.output_dir.resolve())
            return True
        except ValueError:
            return False

    def _title(self, path: Path, lines: list[str]) -> str:
        for line in lines:
            if line.startswith("#"):
                return line.strip("# ").strip() or path.stem
        return path.stem.replace("_", " ").replace("-", " ").title()

    def _purpose(self, lines: list[str], title: str) -> str:
        paragraphs = [line.strip() for line in lines if line.strip() and not line.startswith("#") and not line.startswith("|")]
        return paragraphs[0][:500] if paragraphs else f"Architecture source document: {title}."

    def _sections(self, lines: list[str]) -> list[str]:
        sections = [line.strip("# ").strip() for line in lines if line.startswith("#")]
        return sections or ["Document"]

    def _extract_concepts(self, text: str) -> list[str]:
        phrases = re.findall(r"\b[A-Z][A-Za-z0-9]*(?:[- ][A-Z][A-Za-z0-9]*){1,5}\b", text)
        tokens = re.findall(r"\b[a-z][a-z0-9_/-]{4,}\b", text.lower())
        selected = [phrase.strip() for phrase in phrases if not phrase.isupper()]
        selected.extend(token for token in tokens if token not in STOPWORDS and any(key in token for key in ("graph", "runtime", "mission", "taxonomy", "ontology", "evidence", "publication", "queue")))
        return self._top_items(selected, 30)

    def _match_keywords(self, text: str, mapping: dict[str, tuple[str, ...]]) -> list[str]:
        lowered = text.lower()
        return sorted(name for name, keywords in mapping.items() if any(keyword in lowered for keyword in keywords))

    def _extract_repositories(self, text: str) -> list[str]:
        names = re.findall(r"\b(?:jsp1440/)?orchid-[A-Za-z0-9_-]+|\b(?:jsp1440/)?calyx-[A-Za-z0-9_-]+", text)
        return sorted(set(names))

    def _extract_services(self, text: str) -> list[str]:
        services = re.findall(r"\b[A-Za-z0-9_./-]*(?:Service|Repository|Registry|Router|Engine|Orchestrator)\b", text)
        return sorted(set(services))

    def _extract_dependencies(self, text: str, components: list[str]) -> list[str]:
        deps = set(components)
        for pattern in (r"depends on ([^.:\n]+)", r"requires ([^.:\n]+)", r"between ([^.:\n]+) and ([^.:\n]+)"):
            for match in re.findall(pattern, text, flags=re.IGNORECASE):
                if isinstance(match, tuple):
                    deps.update(part.strip() for part in match)
                else:
                    deps.add(match.strip())
        return sorted(dep for dep in deps if dep)

    def _sentences_matching(self, text: str, keywords: Iterable[str]) -> list[str]:
        prose_lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
        normalized = re.sub(r"\s+", " ", "\n".join(prose_lines))
        sentences = re.split(r"(?<=[.!?])\s+|\n+-\s+", normalized)
        matches = []
        for sentence in sentences:
            lowered = sentence.lower()
            if any(keyword.lower() in lowered for keyword in keywords):
                cleaned = sentence.strip(" -")
                if cleaned:
                    matches.append(cleaned[:240])
        return self._top_items(matches, 8)

    def _provenance(self, document_id: str, relative: str, lines: list[str]) -> list[Provenance]:
        provenance = []
        section = "Document"
        for index, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                section = stripped.strip("# ").strip() or section
            if stripped and any(keyword in stripped.lower() for keywords in DOMAIN_KEYWORDS.values() for keyword in keywords):
                provenance.append(Provenance(document_id, relative, section, index, stripped[:240]))
        return provenance[:12]

    def _canonical_term(self, concept: str) -> str:
        value = concept.strip().lower().replace("_", " ").replace("-", " ")
        value = re.sub(r"\s+", " ", value)
        replacements = {
            "kg": "knowledge graph",
            "oc graph": "knowledge graph",
            "oc taxonomy": "canonical taxonomy",
            "autonomous runtime": "runtime",
        }
        return replacements.get(value, value)

    def _maturity(self, domain: str, matched: list[DocumentRecord]) -> str:
        if any("BUILD-07" in doc.path or "BUILD-06" in doc.path for doc in matched):
            return "implemented and evolving"
        if len(matched) >= 3:
            return "documented foundation"
        if matched:
            return "conceptual foundation"
        return "gap requiring source documentation"

    def _domain_purpose(self, domain: str, matched: list[DocumentRecord]) -> str:
        if matched:
            return f"{domain} is represented by {len(matched)} provenance-linked source document(s), led by {matched[0].title}."
        return f"{domain} is a required architectural domain with insufficient direct source coverage."

    def _domain_responsibilities(self, domain: str, components: list[str]) -> list[str]:
        base = [f"Maintain the canonical responsibilities for {domain}."]
        if components:
            base.append(f"Coordinate with components: {', '.join(components[:6])}.")
        base.append("Preserve provenance, confidence, and owner-reviewed architecture decisions.")
        return base

    def _domain_inputs(self, domain: str, matched: list[DocumentRecord]) -> list[str]:
        values = self._top_items([item for doc in matched for item in doc.datasets + doc.workflows], 5)
        return values or [f"Source documents and implementation evidence related to {domain}."]

    def _domain_outputs(self, domain: str, matched: list[DocumentRecord]) -> list[str]:
        values = self._top_items([item for doc in matched for item in doc.apis + doc.services], 5)
        return values or [f"Provenance-backed architecture decisions for {domain}."]

    def _domain_dependencies(self, domain: str, matched: list[DocumentRecord]) -> list[str]:
        values = self._top_items([item for doc in matched for item in doc.dependencies], 7)
        return values or ["Brain Architect provenance index"]

    def _top_items(self, items: Iterable[str], limit: int) -> list[str]:
        counts: dict[str, int] = {}
        originals: dict[str, str] = {}
        for item in items:
            cleaned = re.sub(r"\s+", " ", item.strip())
            if len(cleaned) < 3:
                continue
            key = cleaned.lower()
            counts[key] = counts.get(key, 0) + 1
            originals.setdefault(key, cleaned)
        ranked = sorted(counts, key=lambda key: (-counts[key], originals[key]))
        return [originals[key] for key in ranked[:limit]]

    def _record_json(self, record: DocumentRecord) -> dict[str, object]:
        data = asdict(record)
        data["provenance"] = [asdict(item) for item in record.provenance]
        return data

    def _domain_json(self, domain: OntologyDomain) -> dict[str, object]:
        data = asdict(domain)
        data["provenance"] = [asdict(item) for item in domain.provenance]
        return data

    def _provenance_index(self, documents: list[DocumentRecord]) -> list[dict[str, object]]:
        return [asdict(item) for document in documents for item in document.provenance]

    def _write_json(self, filename: str, payload: object) -> None:
        (self.output_dir / filename).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _write_markdown(self, filename: str, content: str) -> None:
        (self.output_dir / filename).write_text(self._ascii_markdown(content).rstrip() + "\n", encoding="utf-8")

    def _summary_markdown(self, result: ArchitectureBuildResult) -> str:
        return "\n".join(
            [
                "# BUILD-080 Architecture Summary",
                "",
                f"- Documents ingested: {len(result.documents)}",
                f"- Ontology domains: {len(result.ontology)}",
                f"- Canonical term groups: {len(result.canonical_terms)}",
                f"- Dependency edges: {len(result.dependencies)}",
                f"- Prioritized gaps: {len(result.gaps)}",
                "",
                "This directory is generated by `scripts/build_080_generate_architecture.py`.",
            ]
        )

    def _master_markdown(self, result: ArchitectureBuildResult) -> str:
        lines = [
            "# Orchid Continuum Master Architecture",
            "",
            "## Vision",
            "The Orchid Continuum cultivates understanding by revealing relationships across science, learning, community, conservation, and software systems.",
            "",
            "## Mission",
            "Maintain a traceable, provenance-backed architecture that can guide future builds without modifying production scientific data.",
            "",
            "## System Overview",
            f"BUILD-080 ingested {len(result.documents)} source document(s) and normalized them into {len(result.ontology)} architecture domain(s).",
            "",
        ]
        section_names = [
            "Subsystems",
            "Repositories",
            "Services",
            "Knowledge Graph",
            "Runtime",
            "Educational Architecture",
            "Scientific Architecture",
            "Research Architecture",
            "Brain Architecture",
            "Reasoning Architecture",
            "Historical Architecture",
            "Conservation Architecture",
            "Security",
            "Deployment",
            "Governance",
            "Roadmap",
            "Future Architecture",
            "Open Questions",
            "Known Risks",
            "Architecture Decisions",
        ]
        for section in section_names:
            lines.extend(["", f"## {section}"])
            if section == "Roadmap":
                lines.extend(f"- {item['build']}: {item['purpose']}" for item in result.roadmap[:10])
            elif section == "Known Risks":
                if result.gaps:
                    lines.extend(f"- {gap['priority']}: {gap['area']} - {gap['gap']}" for gap in result.gaps[:10])
                else:
                    lines.append("No blocker-level architecture risks were detected by the BUILD-080 corpus analysis.")
            elif section == "Architecture Decisions":
                lines.extend(
                    [
                        "- Preserve provenance for every canonical statement.",
                        "- Keep BUILD-080 additive and document-only; no runtime, API, migration, or production data changes.",
                        "- Regenerate architecture artifacts through the deterministic pipeline.",
                    ]
                )
            else:
                domain = self._domain_for_section(section, result.ontology)
                if domain:
                    lines.append(domain.purpose)
                    lines.extend(f"- {responsibility}" for responsibility in domain.responsibilities)
                else:
                    lines.append("See `architecture_ontology.json` and `provenance_index.json` for source-linked detail.")
        return "\n".join(lines)

    def _dependency_markdown(self, result: ArchitectureBuildResult) -> str:
        lines = ["# BUILD-080 Dependency Graph", "", "```mermaid", "graph TD"]
        for edge in result.dependencies[:120]:
            source = str(edge["source"]).replace("-", "_")
            target = str(edge["target"]).replace("-", "_")
            lines.append(f"  {source}[{edge['source']}] --> {target}[{edge['target']}]")
        lines.extend(["```", "", "## Edge Provenance"])
        lines.extend(f"- `{edge['source']}` -> `{edge['target']}` from `{edge['provenance_document_id']}`" for edge in result.dependencies[:120])
        return "\n".join(lines)

    def _gap_markdown(self, result: ArchitectureBuildResult) -> str:
        lines = ["# BUILD-080 Gap Analysis", ""]
        if not result.gaps:
            lines.append("No blocker-level architecture gaps were detected in the ingested corpus. Future roadmap items are derived from provenance-linked future-work statements rather than missing required coverage.")
            return "\n".join(lines)
        for gap in result.gaps:
            lines.append(f"- **{gap['priority']}** `{gap['area']}`: {gap['gap']}")
        return "\n".join(lines)

    def _roadmap_markdown(self, result: ArchitectureBuildResult) -> str:
        lines = ["# BUILD-080 Future Build Roadmap", ""]
        for item in result.roadmap:
            lines.extend(
                [
                    f"## {item['build']}",
                    f"- Purpose: {item['purpose']}",
                    f"- Dependencies: {', '.join(item['dependencies'])}",
                    f"- Estimated complexity: {item['estimated_complexity']}",
                    f"- Architectural impact: {item['architectural_impact']}",
                    f"- Recommended sequencing: {item['recommended_sequence']}",
                    f"- Blockers: {', '.join(item['blockers'])}",
                    f"- Expected deliverables: {', '.join(item['expected_deliverables'])}",
                    "",
                ]
            )
        return "\n".join(lines)

    def _domain_for_section(self, section: str, ontology: list[OntologyDomain]) -> OntologyDomain | None:
        aliases = {
            "Knowledge Graph": "Knowledge Graph",
            "Runtime": "Runtime",
            "Educational Architecture": "Educational Intelligence",
            "Scientific Architecture": "Scientific Intelligence",
            "Research Architecture": "Research Intelligence",
            "Brain Architecture": "Planning",
            "Reasoning Architecture": "Reasoning",
            "Historical Architecture": "Historical Intelligence",
            "Conservation Architecture": "Conservation",
            "Security": "Governance",
            "Deployment": "Infrastructure",
            "Governance": "Governance",
            "Future Architecture": "Planning",
        }
        wanted = aliases.get(section)
        return next((domain for domain in ontology if domain.name == wanted), None)

    def _document_id(self, relative_path: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", relative_path.lower()).strip("-")
        return slug[:96]

    def _ascii_markdown(self, text: str) -> str:
        replacements = {
            "\u2014": "-",
            "\u2013": "-",
            "\u2018": "'",
            "\u2019": "'",
            "\u201c": '"',
            "\u201d": '"',
            "\u2022": "-",
            "â€”": "-",
            "â€“": "-",
            "â€¢": "-",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        return text.encode("ascii", errors="replace").decode("ascii")
