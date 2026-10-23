"""Masking of sensitive-looking values in policy passages."""

from sharepoint_policy_mcp.redaction import MASK, redact_text


def test_email_is_masked():
    assert redact_text("escalate to priya.raman@example.com today") == (
        f"escalate to {MASK} today"
    )


def test_ssn_shape_is_masked():
    assert redact_text("subject SSN 123-45-6789") == f"subject SSN {MASK}"


def test_card_shape_is_masked():
    assert redact_text("card 4111 1111 1111 1111 used") == f"card {MASK} used"


def test_several_values_in_one_passage_are_all_masked():
    out = redact_text("a@b.com and 123-45-6789 and 4111111111111111")
    assert "a@b.com" not in out
    assert "123-45-6789" not in out
    assert "4111111111111111" not in out
    assert out.count(MASK) == 3


def test_policy_numbers_survive():
    # An over-eager pattern that eats section numbers out of a policy makes
    # the citation useless.
    text = "See section 5.1 and 314(a); file within 30 calendar days of detection."
    assert redact_text(text) == text


def test_dollar_thresholds_survive():
    text = "more than 10,000 dollars in currency on the same business day"
    assert redact_text(text) == text


def test_disabled_redaction_is_a_passthrough():
    text = "contact a@b.com"
    assert redact_text(text, enabled=False) == text


def test_empty_text_is_safe():
    assert redact_text("") == ""
