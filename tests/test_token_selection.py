"""
Tests for outcome token selection (issue #14).

Before the fix, every order used tokens[0] regardless of the requested outcome,
so a NO order traded the YES token. These tests pin the resolution rules.
"""
import pytest

from polymarket_mcp.tools.trading import resolve_token_id

YES_NO_MARKET = {
    "tokens": [
        {"token_id": "111", "outcome": "Yes"},
        {"token_id": "222", "outcome": "No"},
    ]
}

SPORTS_MARKET = {
    "tokens": [
        {"token_id": "333", "outcome": "Arizona State"},
        {"token_id": "444", "outcome": "Nevada"},
    ]
}

REVERSED_MARKET = {
    "tokens": [
        {"token_id": "555", "outcome": "No"},
        {"token_id": "666", "outcome": "Yes"},
    ]
}


class TestYesNoMarkets:
    """Yes/No markets resolve by outcome label, never by position."""

    def test_yes_selects_yes_token(self):
        token_id, label = resolve_token_id(YES_NO_MARKET, "Yes", "m1")
        assert token_id == "111"
        assert label == "Yes"

    def test_no_selects_no_token(self):
        token_id, label = resolve_token_id(YES_NO_MARKET, "No", "m1")
        assert token_id == "222"
        assert label == "No"

    def test_outcome_is_case_insensitive(self):
        assert resolve_token_id(YES_NO_MARKET, "yes", "m1")[0] == "111"
        assert resolve_token_id(YES_NO_MARKET, "NO", "m1")[0] == "222"

    def test_outcome_is_whitespace_tolerant(self):
        assert resolve_token_id(YES_NO_MARKET, "  No  ", "m1")[0] == "222"

    def test_defaults_to_yes_when_outcome_omitted(self):
        token_id, label = resolve_token_id(YES_NO_MARKET, None, "m1")
        assert token_id == "111"
        assert label == "Yes"

    def test_ignores_token_order(self):
        """The regression: token index must not decide the outcome."""
        assert resolve_token_id(REVERSED_MARKET, "Yes", "m1")[0] == "666"
        assert resolve_token_id(REVERSED_MARKET, "No", "m1")[0] == "555"
        # Default must still find Yes even though it is at index 1.
        assert resolve_token_id(REVERSED_MARKET, None, "m1")[0] == "666"


class TestNonBinaryMarkets:
    """Sports and multi-outcome markets have no Yes/No to fall back on."""

    def test_named_outcome_resolves(self):
        token_id, label = resolve_token_id(SPORTS_MARKET, "Nevada", "m2")
        assert token_id == "444"
        assert label == "Nevada"

    def test_omitted_outcome_raises_instead_of_guessing(self):
        with pytest.raises(ValueError, match="not a Yes/No market"):
            resolve_token_id(SPORTS_MARKET, None, "m2")

    def test_error_lists_available_outcomes(self):
        with pytest.raises(ValueError) as exc:
            resolve_token_id(SPORTS_MARKET, None, "m2")
        assert "Arizona State" in str(exc.value)
        assert "Nevada" in str(exc.value)


class TestErrorHandling:
    def test_unknown_outcome_raises(self):
        with pytest.raises(ValueError, match="not found"):
            resolve_token_id(YES_NO_MARKET, "Maybe", "m1")

    def test_missing_tokens_raises(self):
        with pytest.raises(ValueError, match="No tokens found"):
            resolve_token_id({}, "Yes", "m3")

    def test_empty_tokens_raises(self):
        with pytest.raises(ValueError, match="No tokens found"):
            resolve_token_id({"tokens": []}, "Yes", "m3")

    def test_ambiguous_outcome_raises(self):
        duplicated = {
            "tokens": [
                {"token_id": "1", "outcome": "Yes"},
                {"token_id": "2", "outcome": "Yes"},
            ]
        }
        with pytest.raises(ValueError, match="multiple tokens"):
            resolve_token_id(duplicated, "Yes", "m4")

    def test_blank_outcomes_cannot_be_inferred(self):
        blank = {
            "tokens": [
                {"token_id": "1", "outcome": ""},
                {"token_id": "2", "outcome": ""},
            ]
        }
        with pytest.raises(ValueError, match="not a Yes/No market"):
            resolve_token_id(blank, None, "m5")
