"""Write the synthetic corpus out as .docx files, to exercise ingestion.

The mock corpus lives in Python so the MCP server can serve it without any
files on disk. Ingestion needs the other shape: real Word documents with real
heading styles. Rather than commit binaries, generate them.

    .venv/bin/python tools/make_sample_docs.py sample-policies
    .venv/bin/python -m sharepoint_policy_mcp.ingest sample-policies -o index
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import docx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sharepoint_policy_mcp.corpus import DOCUMENTS, SECTIONS, version_of  # noqa: E402


def safe(name: str) -> str:
    """A title like "BSA/AML Compliance Program Policy" is not a filename."""
    return re.sub(r"[^\w .-]+", "-", name).strip()


def write_document(document, sections, out_dir: Path) -> str:
    filename = f"{document.policy_id} {safe(document.title)} v{document.version}.docx"
    word = docx.Document()
    word.add_heading(document.title, level=0)
    for section in sections:
        # Depth from the section number: "5.1" is a Heading 2 under "5.0".
        level = min(section.number.count(".") + 1, 4)
        word.add_heading(f"{section.number} {section.heading}", level=level)
        word.add_paragraph(section.text)
    word.save(out_dir / filename)
    return filename


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "sample-policies")
    out_dir.mkdir(parents=True, exist_ok=True)

    sidecar: dict[str, dict] = {}
    for document in DOCUMENTS:
        sections = [
            s
            for s in SECTIONS
            if s.policy_id == document.policy_id
            and version_of(s.section_id) == document.version
        ]
        filename = write_document(document, sections, out_dir)
        # The provenance a .docx cannot carry: in production these are the
        # SharePoint columns beside the file.
        sidecar[filename] = {
            "policy_id": document.policy_id,
            "title": document.title,
            "version": document.version,
            "library": document.library,
            "doc_type": document.doc_type,
            "effective_date": document.effective_date,
            "last_modified": document.last_modified,
            "owner": document.owner,
            "url": document.url,
            "superseded": document.superseded,
            "audience": list(document.audience),
        }

    (out_dir / "policies.json").write_text(json.dumps(sidecar, indent=2))
    print(f"Wrote {len(sidecar)} documents and policies.json to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
