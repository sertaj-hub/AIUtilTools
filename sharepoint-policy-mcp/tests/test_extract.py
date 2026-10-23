"""Reading a hierarchy of sections out of a .docx."""

import pytest

from sharepoint_policy_mcp.extract import ExtractionError, extract_docx


def test_title_comes_from_the_title_style(policy_docx):
    assert extract_docx(policy_docx).title == "BSA/AML Compliance Program Policy"


def test_each_heading_becomes_a_section(policy_docx):
    sections = extract_docx(policy_docx).sections
    assert [s.number for s in sections] == ["1.0", "5.0", "5.1"]
    assert [s.heading for s in sections] == [
        "Purpose and Scope",
        "Suspicious Activity Detection",
        "SAR Filing Deadlines",
    ]


def test_body_paragraphs_attach_to_the_preceding_heading(policy_docx):
    sections = {s.number: s for s in extract_docx(policy_docx).sections}
    assert "30 calendar days" in sections["5.1"].text
    assert "120 calendar days" in sections["5.1"].text
    assert "30 calendar days" not in sections["5.0"].text


def test_nesting_produces_the_ancestry_a_citation_needs(policy_docx):
    sections = {s.number: s for s in extract_docx(policy_docx).sections}
    assert sections["5.1"].heading_path == (
        "BSA/AML Compliance Program Policy",
        "5.0 Suspicious Activity Detection",
        "5.1 SAR Filing Deadlines",
    )
    # A top-level section's ancestry is just the document.
    assert sections["1.0"].heading_path == (
        "BSA/AML Compliance Program Policy",
        "1.0 Purpose and Scope",
    )


def test_a_sibling_heading_pops_the_previous_one_off_the_stack(make_docx):
    path = make_docx(
        "x.docx",
        "Doc",
        [
            ("1", "1.0 One"),
            ("2", "1.1 One A"),
            ("p", "body"),
            ("1", "2.0 Two"),
            ("p", "body"),
        ],
    )
    sections = {s.number: s for s in extract_docx(path).sections}
    assert sections["2.0"].heading_path == ("Doc", "2.0 Two")


def test_unnumbered_headings_get_a_positional_number(make_docx):
    path = make_docx("y.docx", "Doc", [("1", "Purpose"), ("p", "body")])
    section = extract_docx(path).sections[0]
    assert section.heading == "Purpose"
    assert section.number == "1"


def test_a_document_with_no_headings_still_yields_its_text(make_docx):
    path = make_docx("z.docx", "", [("p", "A one-page policy with no headings.")])
    extracted = extract_docx(path)
    assert len(extracted.sections) == 1
    assert "one-page policy" in extracted.sections[0].text


def test_an_empty_document_is_an_error_not_a_silent_zero(make_docx):
    path = make_docx("empty.docx", "", [])
    with pytest.raises(ExtractionError, match="no text"):
        extract_docx(path)


def test_a_missing_file_says_so(tmp_path):
    with pytest.raises(ExtractionError, match="No such file"):
        extract_docx(tmp_path / "absent.docx")


def test_a_file_that_is_not_a_docx_is_an_error(tmp_path):
    bogus = tmp_path / "notreally.docx"
    bogus.write_text("this is plain text, not a Word document")
    with pytest.raises(ExtractionError, match="could not be opened"):
        extract_docx(bogus)
