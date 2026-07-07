from app.routers.orchid_widgets import _normalize_genus, _safe_url


def test_normalize_genus_title_cases_valid_input():
    assert _normalize_genus("cAtTlEyA") == "Cattleya"


def test_safe_url_rejects_specimen_and_document_media():
    assert _safe_url("https://example.org/herbarium/specimen-123.jpg") is None
    assert _safe_url("https://example.org/media/plate.pdf") is None


def test_safe_url_accepts_http_photo_candidate():
    assert _safe_url("https://images.example.org/orchids/cattleya.jpg") == "https://images.example.org/orchids/cattleya.jpg"
