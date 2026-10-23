"""Shared fixtures: building .docx policy documents on the fly.

Word files are binary, so rather than commit fixtures the tests write them.
That also means the extraction tests exercise real heading styles rather than
a hand-rolled stand-in for them.
"""

import json

import pytest

docx = pytest.importorskip("docx", reason="python-docx is needed for ingestion tests")


@pytest.fixture
def make_docx(tmp_path):
    """Write a .docx from (level, heading) / paragraph pairs."""

    def build(filename: str, title: str, blocks, directory=None):
        target_dir = directory or tmp_path
        target_dir.mkdir(parents=True, exist_ok=True)
        document = docx.Document()
        if title:
            document.add_heading(title, level=0)
        for kind, value in blocks:
            if kind == "p":
                document.add_paragraph(value)
            else:
                document.add_heading(value, level=int(kind))
        path = target_dir / filename
        document.save(path)
        return path

    return build


@pytest.fixture
def policy_docx(make_docx):
    """A small but realistic two-level policy document."""
    return make_docx(
        "BSA-001 Program Policy v4.2.docx",
        "BSA/AML Compliance Program Policy",
        [
            ("1", "1.0 Purpose and Scope"),
            ("p", "This policy establishes the anti-money laundering programme."),
            ("1", "5.0 Suspicious Activity Detection"),
            ("p", "Alerts are triaged by the first line within five business days."),
            ("2", "5.1 SAR Filing Deadlines"),
            ("p", "A suspicious activity report is filed within 30 calendar days."),
            ("p", "Continuing activity is reported within 120 calendar days."),
        ],
    )


@pytest.fixture
def sidecar(tmp_path):
    def write(mapping):
        (tmp_path / "policies.json").write_text(json.dumps(mapping))
        return tmp_path / "policies.json"

    return write
