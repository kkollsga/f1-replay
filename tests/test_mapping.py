"""Tests for session type bidirectional mapping."""

import pytest
from f1_replay.loaders.core.mapping import to_fastf1_code, to_user_friendly


class TestToFastf1Code:
    """Test user-friendly -> FastF1 code conversion."""

    @pytest.mark.parametrize("user_name,expected", [
        ("Race", "R"),
        ("Qualifying", "Q"),
        ("Sprint", "S"),
        ("Practice1", "FP1"),
        ("Practice2", "FP2"),
        ("Practice3", "FP3"),
    ])
    def test_user_friendly_names(self, user_name, expected):
        assert to_fastf1_code(user_name) == expected

    @pytest.mark.parametrize("code", ["R", "Q", "S", "FP1", "FP2", "FP3"])
    def test_fastf1_codes_passthrough(self, code):
        assert to_fastf1_code(code) == code

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Unknown session type"):
            to_fastf1_code("InvalidSession")

    def test_idempotent(self):
        """Converting twice gives same result."""
        for code in ["R", "Q", "FP1"]:
            assert to_fastf1_code(to_fastf1_code(code)) == code


class TestToUserFriendly:
    """Test FastF1 code -> user-friendly conversion."""

    @pytest.mark.parametrize("code,expected", [
        ("R", "Race"),
        ("Q", "Qualifying"),
        ("S", "Sprint"),
        ("FP1", "Practice1"),
        ("FP2", "Practice2"),
        ("FP3", "Practice3"),
    ])
    def test_known_codes(self, code, expected):
        assert to_user_friendly(code) == expected

    def test_unknown_passthrough(self):
        """Unknown codes are returned as-is."""
        assert to_user_friendly("UNKNOWN") == "UNKNOWN"

    def test_bidirectional(self):
        """User-friendly -> FastF1 -> user-friendly roundtrip."""
        for name in ["Race", "Qualifying", "Practice1"]:
            code = to_fastf1_code(name)
            assert to_user_friendly(code) == name
