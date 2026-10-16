from __future__ import annotations

from app.calyx_conversation.file_analysis import _coerce_csv_value, parse_tabular_file


class TestCoerceCsvValueUnderscore:
    """Test _coerce_csv_value with underscore-containing cells."""

    def test_underscore_in_integer_like_cell_stays_text(self):
        """Cells containing underscore are never coerced to numbers."""
        assert _coerce_csv_value("2024_01") == "2024_01"

    def test_underscore_in_float_like_cell_stays_text(self):
        """Cells with underscores and decimals stay as text."""
        assert _coerce_csv_value("1_000.5") == "1_000.5"

    def test_underscore_with_spaces_stays_text(self):
        """Cells with underscores and leading/trailing spaces stay as text."""
        assert _coerce_csv_value(" 2024_01 ") == "2024_01"

    def test_underscore_in_mixed_number_text_stays_text(self):
        """Various underscore patterns stay as text."""
        assert _coerce_csv_value("1_234") == "1_234"
        assert _coerce_csv_value("_100") == "_100"
        assert _coerce_csv_value("100_") == "100_"
        assert _coerce_csv_value("1_0_0") == "1_0_0"

    def test_regular_integer_coerces_to_int(self):
        """Regular integers without underscores coerce normally."""
        assert _coerce_csv_value("12") == 12
        assert isinstance(_coerce_csv_value("12"), int)

    def test_integer_with_spaces_coerces_to_int(self):
        """Integers with leading/trailing spaces coerce to int."""
        assert _coerce_csv_value(" 7 ") == 7
        assert isinstance(_coerce_csv_value(" 7 "), int)

    def test_regular_float_coerces_to_float(self):
        """Regular floats without underscores coerce normally."""
        assert _coerce_csv_value("1.5") == 1.5
        assert isinstance(_coerce_csv_value("1.5"), float)

    def test_true_coerces_to_boolean(self):
        """'true' coerces to True boolean."""
        assert _coerce_csv_value("true") is True
        assert _coerce_csv_value("TRUE") is True
        assert _coerce_csv_value("True") is True

    def test_false_coerces_to_boolean(self):
        """'false' coerces to False boolean."""
        assert _coerce_csv_value("false") is False
        assert _coerce_csv_value("FALSE") is False
        assert _coerce_csv_value("False") is False

    def test_empty_string_coerces_to_none(self):
        """Empty string coerces to None."""
        assert _coerce_csv_value("") is None
        assert _coerce_csv_value("  ") is None

    def test_regular_text_stays_text(self):
        """Regular text without special patterns stays as text."""
        assert _coerce_csv_value("hello") == "hello"
        assert _coerce_csv_value("abc123") == "abc123"


class TestParseTabularFileUnderscore:
    """Test parse_tabular_file with underscore-containing cells."""

    def test_parse_csv_with_underscore_cells_keeps_as_text(self):
        """CSV with underscore-containing cells keeps them as text."""
        parsed = parse_tabular_file(
            b"batch,count\n2024_01,3\n",
            "x.csv",
        )
        assert parsed["columns"]["batch"] == ["2024_01"]
        assert parsed["columns"]["count"] == [3]

    def test_parse_csv_with_multiple_underscore_cells(self):
        """Multiple underscore-containing cells are preserved."""
        parsed = parse_tabular_file(
            b"id,value,amount\n2024_01,1_000.5,42\n2024_02,2_000,100\n",
            "x.csv",
        )
        assert parsed["columns"]["id"] == ["2024_01", "2024_02"]
        assert parsed["columns"]["value"] == ["1_000.5", "2_000"]
        assert parsed["columns"]["amount"] == [42, 100]

    def test_parse_csv_mixed_with_regular_numbers(self):
        """Mix of underscore and regular numbers handled correctly."""
        parsed = parse_tabular_file(
            b"code,normal_int,normal_float\nABC_123,456,7.8\n",
            "x.csv",
        )
        assert parsed["columns"]["code"] == ["ABC_123"]
        assert parsed["columns"]["normal_int"] == [456]
        assert parsed["columns"]["normal_float"] == [7.8]
