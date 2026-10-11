"""Offline scientific workflow: Lexicon -> Morphology -> Matrix -> Dossier.

Additive, deterministic integration layer connecting the existing Orchid
Continuum scientific components (Lexicon facade payload shapes, literature
extraction contracts, Matrix Identification engine, Species Dossier envelope,
Knowledge Graph models, OAO curated accessions from Brain PR #230) through
fixture-driven tests.  No production writes, no live provider calls, no paid
services, no fabricated evidence.
"""

from .evidence import CharacterEvidenceStore
from .extraction import CHARACTERS, extract_characters, parse_description_text
from .glossary import IllustrationRegistry, build_glossary_entry, build_glossary_index
from .models import (
    CharacterObservationRecord,
    CharacterStateView,
    EvidenceKind,
    ProvenanceMethod,
    SourceCitation,
    StateKind,
    TextSpan,
)
from .taxonomy import FixtureTaxonResolver, TaxonRecord, TaxonResolution
from .terminology import CuratedTerminologyService, LexiconTerm, TermMatch
from .workflow import FixtureLayout, WorkflowResult, run_workflow

__all__ = [
    "CHARACTERS",
    "CharacterEvidenceStore",
    "CharacterObservationRecord",
    "CharacterStateView",
    "CuratedTerminologyService",
    "EvidenceKind",
    "FixtureLayout",
    "FixtureTaxonResolver",
    "IllustrationRegistry",
    "LexiconTerm",
    "ProvenanceMethod",
    "SourceCitation",
    "StateKind",
    "TaxonRecord",
    "TaxonResolution",
    "TermMatch",
    "TextSpan",
    "WorkflowResult",
    "build_glossary_entry",
    "build_glossary_index",
    "extract_characters",
    "parse_description_text",
    "run_workflow",
]
