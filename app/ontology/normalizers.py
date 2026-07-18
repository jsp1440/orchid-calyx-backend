import re
import unicodedata


def normalize_ontology_text(value: str, *, scientific_name: bool = False) -> str:
    """Normalize lookup text without inferring or correcting taxonomic meaning."""
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = re.sub(r"[\s\u00a0]+", " ", normalized)
    normalized = normalized.casefold()
    normalized = re.sub(r"[‐‑‒–—]", "-", normalized)
    normalized = re.sub(r"[.,;:!?()\[\]{}'\"]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if scientific_name:
        normalized = re.sub(r"\s+x\s+", " × ", normalized)
    return normalized


def normalize_canonical_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        raise ValueError("EMPTY_CANONICAL_KEY")
    return re.sub(r"\s+", "_", normalized).casefold()
