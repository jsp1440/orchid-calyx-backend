from uuid import uuid4

from app.concepts.lexical import DefinitionType, LabelType, normalize_lexical_value
from app.concepts.services import ConceptRegistryService


class FakeConceptRepository:
    def __init__(self):
        self.concept_id = uuid4()
        self.labels = []
        self.definitions = []

    def get_concept(self, identifier):
        if identifier == self.concept_id:
            return {"concept_id": self.concept_id, "concept_uri": f"https://id.orchidcontinuum.org/concept/{self.concept_id}"}
        return None

    def create_label(self, data):
        self.labels.append(dict(data))
        return dict(data)

    def list_labels(self, concept_id, language=None):
        return [row for row in self.labels if row["concept_id"] == concept_id and (language is None or row["language"] == language)]

    def search_labels(self, normalized_query, language=None, limit=25):
        rows = [row for row in self.labels if row["normalized_label"].startswith(normalized_query)]
        if language is not None:
            rows = [row for row in rows if row["language"] == language]
        return rows[:limit]

    def create_definition(self, data):
        self.definitions.append(dict(data))
        return dict(data)

    def list_definitions(self, concept_id, language=None):
        return [row for row in self.definitions if row["concept_id"] == concept_id and (language is None or row["language"] == language)]


def test_normalization_is_deterministic_and_unicode_aware():
    assert normalize_lexical_value("  Cattleya—Alliance  ") == "cattleya-alliance"
    assert normalize_lexical_value("CATTLEYA alliance") == "cattleya alliance"


def test_create_and_resolve_preferred_label():
    repo = FakeConceptRepository()
    service = ConceptRegistryService(repo)
    service.create_label(
        concept_id=repo.concept_id,
        label_type=LabelType.PREFERRED,
        label="Cattleya alliance",
        language="en",
        actor="tester",
    )
    result = service.search("Cattleya alliance", language="en")
    assert result["status"] == "RESOLVED"
    assert result["matches"][0]["concept_id"] == repo.concept_id


def test_ambiguous_exact_matches_are_not_guessed():
    repo = FakeConceptRepository()
    service = ConceptRegistryService(repo)
    other = uuid4()
    repo.labels.extend(
        [
            {
                "label_id": uuid4(),
                "concept_id": repo.concept_id,
                "label_type": LabelType.PREFERRED.value,
                "label": "Spider orchid",
                "normalized_label": "spider orchid",
                "language": "en",
                "editorial_context": "default",
                "review_state": "APPROVED",
            },
            {
                "label_id": uuid4(),
                "concept_id": other,
                "label_type": LabelType.COMMON_NAME.value,
                "label": "Spider orchid",
                "normalized_label": "spider orchid",
                "language": "en",
                "editorial_context": "default",
                "review_state": "APPROVED",
            },
        ]
    )
    result = service.search("Spider orchid", language="en")
    assert result["status"] == "AMBIGUOUS"
    assert len(result["matches"]) == 2


def test_definition_creation_preserves_audience_variant():
    repo = FakeConceptRepository()
    service = ConceptRegistryService(repo)
    definition = service.create_definition(
        concept_id=repo.concept_id,
        definition_type=DefinitionType.LEARNER,
        text="A simplified explanation for learners.",
        language="en",
        actor="tester",
    )
    assert definition["definition_type"] == DefinitionType.LEARNER.value
    assert definition["text"].startswith("A simplified")
