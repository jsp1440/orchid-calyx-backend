from __future__ import annotations

from app.data_intelligence.service import (
    _aggregate,
    _coerce_number,
    _infer_type,
    _sort_key,
)


class TestCoerceNumber:
    """Test _coerce_number with finite and non-finite values."""

    def test_coerce_number_nan_string(self):
        """Text 'nan' parses to NaN, which is non-finite, should return None."""
        assert _coerce_number("nan") is None

    def test_coerce_number_inf_string(self):
        """Text 'inf' parses to infinity, which is non-finite, should return None."""
        assert _coerce_number("inf") is None

    def test_coerce_number_infinity_string(self):
        """Text 'infinity' parses to infinity, which is non-finite, should return None."""
        assert _coerce_number("infinity") is None

    def test_coerce_number_neg_inf_string(self):
        """Text '-inf' parses to negative infinity, which is non-finite, should return None."""
        assert _coerce_number("-inf") is None

    def test_coerce_number_1e999_string(self):
        """Text '1e999' parses to infinity (overflow), which is non-finite, should return None."""
        assert _coerce_number("1e999") is None

    def test_coerce_number_finite_decimal(self):
        """Text '2.5' parses to finite 2.5, should return 2.5."""
        assert _coerce_number("2.5") == 2.5

    def test_coerce_number_finite_integer_string(self):
        """Text '42' parses to finite 42.0, should return 42.0."""
        assert _coerce_number("42") == 42.0

    def test_coerce_number_int_input(self):
        """Int input 42 should return 42.0."""
        assert _coerce_number(42) == 42.0

    def test_coerce_number_float_input(self):
        """Float input 2.5 should return 2.5."""
        assert _coerce_number(2.5) == 2.5

    def test_coerce_number_bool_input(self):
        """Bool input (True or False) should return None."""
        assert _coerce_number(True) is None
        assert _coerce_number(False) is None

    def test_coerce_number_none_input(self):
        """None input should return None."""
        assert _coerce_number(None) is None

    def test_coerce_number_empty_string(self):
        """Empty string should return None."""
        assert _coerce_number("") is None

    def test_coerce_number_whitespace_string(self):
        """Whitespace-only string should return None."""
        assert _coerce_number("   ") is None

    def test_coerce_number_non_numeric_string(self):
        """Non-numeric text should return None."""
        assert _coerce_number("abc") is None


class TestInferType:
    """Test _infer_type with non-finite values."""

    def test_infer_type_nan_inf_returns_text(self):
        """Values that parse to non-finite should be inferred as 'text'."""
        assert _infer_type(["nan", "inf"]) == "text"

    def test_infer_type_mixed_nan_and_text(self):
        """Mix of non-finite and other text should be 'text'."""
        assert _infer_type(["nan", "hello"]) == "text"

    def test_infer_type_finite_numbers(self):
        """Finite text numbers should be inferred as 'number'."""
        assert _infer_type(["2.5", "3.0", "1.5"]) == "number"

    def test_infer_type_integers(self):
        """Integer strings should be inferred as 'integer'."""
        assert _infer_type(["1", "2", "3"]) == "integer"


class TestAggregate:
    """Test _aggregate with non-finite values."""

    def test_aggregate_mean_with_nan_string(self):
        """_aggregate(['1', '2', 'NaN'], 'mean') should return 1.5, excluding NaN."""
        result = _aggregate(["1", "2", "NaN"], "mean")
        assert result == 1.5

    def test_aggregate_sum_with_inf_string(self):
        """_aggregate(['1', 'inf'], 'sum') should return 1.0, excluding inf."""
        result = _aggregate(["1", "inf"], "sum")
        assert result == 1.0

    def test_aggregate_mean_with_mixed_nonfinite(self):
        """Non-finite values should be excluded from mean calculation."""
        result = _aggregate(["1", "2", "3", "nan", "inf"], "mean")
        assert result == 2.0

    def test_aggregate_sum_numeric_inputs(self):
        """Sum should work with numeric inputs."""
        result = _aggregate([1, 2, 3], "sum")
        assert result == 6

    def test_aggregate_min_with_nonfinite(self):
        """Min should exclude non-finite values."""
        result = _aggregate(["1", "2", "3", "inf"], "min")
        assert result == 1.0

    def test_aggregate_max_with_nonfinite(self):
        """Max should exclude non-finite values."""
        result = _aggregate(["1", "2", "3", "nan"], "max")
        assert result == 3.0


class TestSortKey:
    """Test _sort_key with non-finite values."""

    def test_sort_with_nan_string(self):
        """sorted(['3', 'nan', '1', '2'], key=_sort_key) should return ['1', '2', '3', 'nan']."""
        values = ["3", "nan", "1", "2"]
        sorted_values = sorted(values, key=_sort_key)
        assert sorted_values == ["1", "2", "3", "nan"]

    def test_sort_with_inf_string(self):
        """Non-finite values should sort at the end."""
        values = ["5", "inf", "1", "2"]
        sorted_values = sorted(values, key=_sort_key)
        assert sorted_values == ["1", "2", "5", "inf"]

    def test_sort_with_multiple_nonfinite(self):
        """Multiple non-finite values should sort at the end."""
        values = ["5", "inf", "nan", "1", "2"]
        sorted_values = sorted(values, key=_sort_key)
        # Non-finite values become text and sort alphabetically at the end
        assert sorted_values[0:3] == ["1", "2", "5"]
        assert set(sorted_values[3:]) == {"inf", "nan"}

    def test_sort_with_text_and_numbers(self):
        """Text values should sort after numbers but before missing values."""
        values = ["3", "apple", "1", "2", "zebra"]
        sorted_values = sorted(values, key=_sort_key)
        # Numbers first, then text alphabetically
        assert sorted_values[0:3] == ["1", "2", "3"]
        assert sorted_values[3:5] == ["apple", "zebra"]

    def test_sort_with_missing_values(self):
        """Missing values should sort at the end."""
        values = ["3", "1", None, "2", ""]
        sorted_values = sorted(values, key=_sort_key)
        # Numbers first, then missing at the end
        assert sorted_values[0:3] == ["1", "2", "3"]
        assert sorted_values[3:5] == [None, ""]
