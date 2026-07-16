import re
from hashlib import sha256
from .schemas import ExtractionResult, IntakeEntity, IntakeRelationship, IntakeTask

PARSER_VERSION = "build-070-rules-v1"

SPECIES_PATTERN = re.compile(r"\b([A-Z][a-z]{2,})\s+([a-z][a-z-]{2,})\b")
DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)
URL_PATTERN = re.compile(r"https?://[^\s)]+", re.I)
DEADLINE_PATTERN = re.compile(r"\b(?:deadline|closing|closes|before)\s+(?:on\s+)?([A-Z][a-z]+\s+\d{1,2},\s+20\d{2})", re.I)
ORG_SUFFIX = r"(?:Initiative|Fund|Foundation|Garden|Gardens|Institute|University|Society|Consortium|Department|Agency|Center|Centre)"
ORG_PATTERN = re.compile(rf"\b([A-Z][A-Za-z&'’.-]*(?:\s+[A-Z][A-Za-z&'’.-]*){{0,7}}\s+{ORG_SUFFIX})\b")


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _entity(entity_type: str, name: str, exact: str, confidence: float, **metadata) -> IntakeEntity:
    return IntakeEntity(
        entity_type=entity_type,
        canonical_name=name.strip(),
        normalized_name=normalize(name),
        confidence=confidence,
        exact_text=exact,
        metadata=metadata,
    )


def extract(content: str) -> ExtractionResult:
    entities: dict[tuple[str, str], IntakeEntity] = {}
    relationships: list[IntakeRelationship] = []
    tasks: list[IntakeTask] = []

    for match in SPECIES_PATTERN.finditer(content):
        name = f"{match.group(1)} {match.group(2)}"
        # Conservative botanical filter: exclude ordinary title-case phrases.
        nearby = content[max(0, match.start() - 80):match.end() + 80].lower()
        if any(marker in nearby for marker in ("orchid", "species", "described", "taxon", "endemic")):
            entities[("species", normalize(name))] = _entity("species", name, match.group(0), 0.86)

    for match in DOI_PATTERN.finditer(content):
        value = match.group(0).rstrip(".,;")
        entities[("identifier", normalize(value))] = _entity("identifier", value, match.group(0), 0.99, scheme="doi")

    for match in URL_PATTERN.finditer(content):
        value = match.group(0).rstrip(".,;")
        entities[("api_or_url", normalize(value))] = _entity("api_or_url", value, match.group(0), 0.98)

    for match in DEADLINE_PATTERN.finditer(content):
        value = match.group(1)
        entities[("deadline", normalize(value))] = _entity("deadline", value, match.group(0), 0.95)
        tasks.append(IntakeTask(task_type="review_deadline", title=f"Review deadline: {value}", priority="HIGH", rationale=match.group(0)))

    for match in ORG_PATTERN.finditer(content):
        value = match.group(1).strip()
        entities[("organization", normalize(value))] = _entity("organization", value, match.group(0), 0.82)

    lower = content.lower()
    if any(word in lower for word in ("grant", "funding", "applications open")):
        tasks.append(IntakeTask(task_type="review_funding", title="Review funding opportunity", priority="HIGH", rationale="Funding language detected in source."))
    if "new species" in lower or "formally described" in lower or "species description" in lower:
        tasks.append(IntakeTask(task_type="verify_taxonomy", title="Verify newly described taxa", priority="HIGH", rationale="Taxonomic novelty language detected."))
    if "api" in lower:
        tasks.append(IntakeTask(task_type="review_api", title="Review referenced API or integration", priority="MEDIUM", rationale="API language detected."))

    species = [e for e in entities.values() if e.entity_type == "species"]
    organizations = [e for e in entities.values() if e.entity_type == "organization"]
    for sp in species:
        for org in organizations[:3]:
            relationships.append(IntakeRelationship(
                subject_name=sp.canonical_name,
                predicate="mentioned_with",
                object_name=org.canonical_name,
                confidence=0.45,
                evidence_text="Both entities occur in the same submitted source; human review required.",
            ))

    return ExtractionResult(
        entities=list(entities.values()),
        relationships=relationships,
        tasks=tasks,
        parser_version=PARSER_VERSION,
    )


def content_hash(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()
