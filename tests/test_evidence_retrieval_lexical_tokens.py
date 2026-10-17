from hashlib import sha256

from app.evidence_retrieval.engine import (
    RetrievalEngine,
    query_terms,
    term_occurrences,
    tokenize,
)
from app.evidence_retrieval.models import RetrievalQuery
from app.semantic_index.memory_repository import MemoryIndexRepository
from app.semantic_index.provider import DeterministicLocalProvider

TEXTS = (
    "Exemplaria nivea is pollinated by euglossine bees.",
    "Orchids of the Andes: a checklist.",
    "Thermal tolerance in the genus Exemplaria.",
)


def engine():
    repo = MemoryIndexRepository()
    provider = DeterministicLocalProvider()
    model = repo.ensure_model(provider.metadata)
    for i, text in enumerate(TEXTS, start=1):
        repo.documents.append(
            {
                "index_document_id": i,
                "source_object_type": "PASSAGE",
                "source_object_id": i,
                "revision_id": i,
                "parent_type": "PASSAGE",
                "parent_id": i,
                "anchors": (i,),
                "content_hash": sha256(text.encode()).hexdigest(),
                "metadata_hash": str(i),
                "model_id": model,
                "configuration_hash": "c",
                "active": True,
                "version": 1,
                "metadata": {
                    "display_policy": "FULL_TEXT_ALLOWED",
                    "document_id": f"doc-{i}",
                },
            }
        )
        repo.lexical.append(
            {
                "index_document_id": i,
                "normalized_text": text.casefold(),
                "verbatim_text": text,
                "language": "en",
                "title": "",
            }
        )
        repo.vectors.append(
            {
                "index_document_id": i,
                "vector": provider.embed_batch([text])[0],
                "active": True,
            }
        )
    return RetrievalEngine(repo, provider)


def lexical_ids(text):
    result = engine().search(RetrievalQuery(text, mode="LEXICAL"))
    return [r["citation"]["document_id"] for r in result["results"]]


def test_query_terms_drop_stopwords_punctuation_and_duplicates():
    assert query_terms("Which pollinators visit Exemplaria nivea? Nivea!") == [
        "pollinators",
        "visit",
        "exemplaria",
        "nivea",
    ]
    assert tokenize("x-ray, d'Orbigny's") == ["x-ray", "d'orbigny's"]


def test_stopword_only_query_matches_nothing():
    assert lexical_ids("what is the a of") == []


def test_function_words_no_longer_match_every_document():
    # Before the fix "the" and "a" matched all three passages as substrings.
    assert lexical_ids("the nivea") == ["doc-1"]


def test_trailing_punctuation_does_not_block_a_match():
    assert lexical_ids("nivea?") == ["doc-1"]


def test_short_terms_need_whole_tokens_and_long_terms_match_prefixes_only():
    tokens = tokenize("Orchids thermal Exemplaria")
    assert term_occurrences("orchid", tokens) == 1
    assert term_occurrences("chid", tokens) == 0
    assert term_occurrences("the", tokens) == 0
    assert term_occurrences("exemplaria", tokens) == 1
    assert lexical_ids("orchid") == ["doc-2"]


def test_ranking_version_records_the_matching_change():
    result = engine().search(RetrievalQuery("nivea", mode="LEXICAL"))
    assert result["ranking_configuration_version"] == "085b-rank-2"
    assert result["results"][0]["citation"]["ranking_version"] == "085b-rank-2"
