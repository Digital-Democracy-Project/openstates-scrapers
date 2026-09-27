import logging

from utils.votes import safe_lookup


def test_safe_lookup_returns_mapped_value_on_a_hit():
    assert safe_lookup({"Yea": "yes"}, "Yea", what="vote choice") == "yes"


def test_safe_lookup_returns_none_and_warns_on_a_miss(caplog):
    with caplog.at_level(logging.WARNING, logger="openstates"):
        result = safe_lookup({"Yea": "yes"}, "Present", what="vote choice")

    assert result is None
    assert "Unmapped vote choice: 'Present'" in caplog.text


def test_safe_lookup_warning_includes_context_when_given(caplog):
    with caplog.at_level(logging.WARNING, logger="openstates"):
        safe_lookup({}, "Concurrent Resolution Rejected", what="Senate vote result", context="https://example.com/vote123")

    assert "https://example.com/vote123" in caplog.text
