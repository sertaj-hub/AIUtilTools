from servicenow_mcp.config import DEFAULT_REDACTED_FIELDS
from servicenow_mcp.redaction import MASK, redact_record, redact_records, redact_value

FIELDS = DEFAULT_REDACTED_FIELDS


def test_sensitive_field_is_masked_but_key_kept():
    out = redact_record({"number": "INC1", "email": "a@b.com"}, FIELDS)
    assert out["number"] == "INC1"
    assert out["email"] == MASK
    assert "email" in out  # key preserved so the caller knows it was withheld


def test_suffix_match_catches_custom_fields():
    out = redact_record({"u_customer_email": "x@y.com", "caller_phone": "123"}, FIELDS)
    assert out["u_customer_email"] == MASK
    assert out["caller_phone"] == MASK


def test_unrelated_field_named_like_prefix_is_not_masked():
    # "emailed_at" should not match the "email" rule.
    out = redact_record({"emailed_at": "2026-01-01"}, FIELDS)
    assert out["emailed_at"] == "2026-01-01"


def test_empty_sensitive_value_is_left_alone():
    out = redact_record({"email": "", "phone": None}, FIELDS)
    assert out["email"] == ""
    assert out["phone"] is None


def test_email_inside_free_text_is_masked():
    out = redact_record(
        {"description": "Contact priya.raman@example.com for details"}, FIELDS
    )
    assert "priya.raman@example.com" not in out["description"]
    assert MASK in out["description"]


def test_ssn_and_card_patterns_in_free_text():
    out = redact_record({"comments": "SSN 123-45-6789 card 4111111111111111"}, FIELDS)
    assert "123-45-6789" not in out["comments"]
    assert "4111111111111111" not in out["comments"]


def test_redaction_can_be_disabled():
    out = redact_record({"email": "a@b.com"}, FIELDS, enabled=False)
    assert out["email"] == "a@b.com"


def test_nested_structures_are_walked():
    value = redact_value({"a": ["x@y.com", {"b": "z@w.com"}]})
    assert value["a"][0] == MASK
    assert value["a"][1]["b"] == MASK


def test_original_record_is_not_mutated():
    original = {"email": "a@b.com"}
    redact_record(original, FIELDS)
    assert original["email"] == "a@b.com"


def test_redact_records_maps_over_list():
    out = redact_records([{"email": "a@b.com"}, {"email": "c@d.com"}], FIELDS)
    assert [r["email"] for r in out] == [MASK, MASK]
