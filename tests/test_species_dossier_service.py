from app.species_dossier.models import FederationResolveRequest
from app.species_dossier.service import SpeciesDossierService, extract_species_name_from_url, normalize_scientific_name


class FakeRepository:
    def get_dossier(self, taxon_id):
        return None

    def get_atlas(self, taxon_id):
        return None

    def resolve_taxon_id(self, taxon_id):
        if taxon_id == "oc:1":
            return ("oc:1", "Dracula vampira")
        return None

    def resolve_name(self, normalized_name):
        if normalized_name == "Dracula vampira":
            return [("oc:1", "Dracula vampira", "accepted_name")]
        if normalized_name == "Masdevallia vampira":
            return [("oc:1", "Dracula vampira", "synonym")]
        if normalized_name == "Epidendrum ambiguum":
            return [
                ("oc:2", "Epidendrum alpha", "synonym"),
                ("oc:3", "Epidendrum beta", "synonym"),
            ]
        return []

    def resolve_partner_slug(self, partner_slug, species_slug):
        if partner_slug == "iospe" and species_slug == "dracvampira":
            return [("oc:1", "Dracula vampira", "partner_slug")]
        return []


def test_normalizes_binomial_and_discards_author_string():
    assert normalize_scientific_name("Dracula vampira Luer") == "Dracula vampira"


def test_extracts_species_from_url_slug():
    assert extract_species_name_from_url("https://example.org/species/Dracula_vampira") == "Dracula vampira"


def test_resolves_canonical_taxon_id():
    result = SpeciesDossierService(FakeRepository()).resolve(FederationResolveRequest(taxon_id="oc:1"))
    assert result.status == "resolved"
    assert result.taxon_id == "oc:1"
    assert result.match_state == "taxon_id"


def test_resolves_synonym_to_canonical_dossier():
    result = SpeciesDossierService(FakeRepository()).resolve(FederationResolveRequest(name="Masdevallia vampira"))
    assert result.status == "resolved"
    assert result.matched_name == "Dracula vampira"
    assert result.match_state == "synonym"
    assert result.canonical_dossier_url.endswith("/species/oc:1")


def test_partner_slug_uses_one_adaptive_integration():
    result = SpeciesDossierService(FakeRepository()).resolve(
        FederationResolveRequest(partner_slug="iospe", partner_species_slug="dracvampira")
    )
    assert result.status == "resolved"
    assert result.match_state == "partner_slug"


def test_ambiguous_name_fails_closed():
    result = SpeciesDossierService(FakeRepository()).resolve(FederationResolveRequest(name="Epidendrum ambiguum"))
    assert result.status == "ambiguous"
    assert len(result.candidates) == 2
    assert result.taxon_id is None


def test_unresolved_name_does_not_guess():
    result = SpeciesDossierService(FakeRepository()).resolve(FederationResolveRequest(name="Unknown orchid"))
    assert result.status in {"invalid", "unresolved"}
    assert result.taxon_id is None
