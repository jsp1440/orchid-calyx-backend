from runtime.cultivated_identity import resolve_cultivated_identity


def test_plain_species_and_named_clone_resolve_without_rewriting_identity() -> None:
    species = resolve_cultivated_identity("Phragmipedium kovachii")
    assert species is not None
    assert species.species == "Phragmipedium kovachii"
    assert species.relationship == "species"

    clone = resolve_cultivated_identity("Phragmipedium kovachii 'Daniela'")
    assert clone is not None
    assert clone.cultivated == "Phragmipedium kovachii 'Daniela'"
    assert clone.species == "Phragmipedium kovachii"
    assert clone.relationship == "cultivar_of_species"


def test_am1_same_species_clone_cross_has_explicit_relationship() -> None:
    label = "Phragmipedium kovachii 'Daniela' × Phragmipedium kovachii 'Maria'"
    resolved = resolve_cultivated_identity(label)

    assert resolved is not None
    assert resolved.cultivated == label
    assert resolved.species == "Phragmipedium kovachii"
    assert resolved.genus == "Phragmipedium"
    assert resolved.relationship == "cross_within_species"


def test_standard_same_species_shorthand_is_supported() -> None:
    labels = [
        "Phragmipedium kovachii 'Daniela' × 'Maria'",
        "Phragmipedium kovachii ('Daniela' × 'Maria')",
        "Phrag. kovachii 'Daniela' x 'Maria'",
    ]
    for label in labels:
        resolved = resolve_cultivated_identity(label)
        assert resolved is not None
        assert resolved.species == "Phragmipedium kovachii"
        assert resolved.relationship == "cross_within_species"


def test_interspecific_cross_refuses_first_parent_and_genus_fallback() -> None:
    labels = [
        "Phragmipedium besseae × Phragmipedium kovachii",
        "Phragmipedium besseae × kovachii",
        "Phrag. Ingrid Suarez (humboldtii × kovachii)",
    ]
    for label in labels:
        resolved = resolve_cultivated_identity(label)
        assert resolved is not None
        assert resolved.species is None
        assert resolved.relationship == "none"
        assert resolved.reason


def test_grex_and_ambiguous_capitalisation_fail_closed() -> None:
    grex = resolve_cultivated_identity("Phragmipedium Memoria Dick Clements")
    assert grex is not None
    assert grex.species is None
    assert grex.relationship == "none"

    ambiguous = resolve_cultivated_identity("Phrag. Kovachii")
    assert ambiguous is not None
    assert ambiguous.species is None
    assert ambiguous.reason is not None
    assert "capitalised" in ambiguous.reason


def test_missing_genus_is_reported_instead_of_inferred() -> None:
    resolved = resolve_cultivated_identity("kovachii")
    assert resolved is not None
    assert resolved.species is None
    assert resolved.genus is None
    assert resolved.reason is not None
    assert "No genus" in resolved.reason


def test_malformed_or_unsafe_identity_is_rejected() -> None:
    assert resolve_cultivated_identity(None) is None
    assert resolve_cultivated_identity("") is None
    assert resolve_cultivated_identity("<script>") is None
    assert resolve_cultivated_identity("Phragmipedium\nkovachii") is None
    assert resolve_cultivated_identity("Phragmipedium\\\\nkovachii") is None
    assert resolve_cultivated_identity("x" * 241) is None
