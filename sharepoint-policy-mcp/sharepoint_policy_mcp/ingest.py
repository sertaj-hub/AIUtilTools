"""The ingestion pipeline: documents on disk -> chunks + vectors on disk.

Run it over a folder of .docx policies and it writes three files: the chunks
with their metadata, the embedding index, and a manifest of content hashes so
the next run only re-embeds what changed.

What a .docx cannot tell you is its own provenance -- which policy id it is,
which version, who owns it, who may read it. In production that comes from
the SharePoint columns next to the file. Here it comes from a `policies.json`
sidecar, falling back to the filename, and whatever had to be guessed is
reported rather than quietly assumed. A citation whose version was inferred
from a filename is a citation that can be wrong in the one field an examiner
will check.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .chunking import DEFAULT_MAX_CHARS, DEFAULT_OVERLAP_CHARS, chunk_section
from .embedder import Embedder, HashingEmbedder
from .extract import ExtractionError, extract_docx
from .models import Chunk, Document
from .vectors import VectorIndex

CHUNKS_FILE = "chunks.json"
VECTORS_FILE = "vectors.npz"
MANIFEST_FILE = "manifest.json"

# "BSA-001 Program Policy v4.2.docx" -> ("BSA-001", "4.2")
_FILENAME_RE = re.compile(
    r"^(?P<policy>[A-Za-z]{2,5}-\d{1,4})\b.*?\bv(?P<version>\d+(?:\.\d+)*)\s*$"
)
_DOC_TYPE_RE = re.compile(r"^([A-Za-z]{2,5})-")


@dataclass
class SourceReport:
    path: str
    policy_id: str
    version: str
    sections: int
    chunks: int
    inferred: list[str] = field(default_factory=list)
    skipped_reason: str | None = None


@dataclass
class IngestResult:
    out_dir: str
    embedder: str
    is_semantic: bool
    total_chunks: int
    sources: list[SourceReport]

    @property
    def reused(self) -> list[SourceReport]:
        return [s for s in self.sources if s.skipped_reason == "unchanged"]

    @property
    def failed(self) -> list[SourceReport]:
        return [
            s
            for s in self.sources
            if s.skipped_reason is not None and s.skipped_reason != "unchanged"
        ]


def file_digest(path: Path) -> str:
    digest = hashlib.blake2b(path.read_bytes(), digest_size=16)
    return digest.hexdigest()


def parse_filename(stem: str) -> tuple[str | None, str | None]:
    match = _FILENAME_RE.match(stem.strip())
    if not match:
        return None, None
    return match.group("policy").upper(), match.group("version")


def load_sidecar(directory: Path) -> dict[str, dict]:
    """Read `policies.json`, keyed by filename, if the author provided one."""
    sidecar = directory / "policies.json"
    if not sidecar.exists():
        return {}
    try:
        data = json.loads(sidecar.read_text())
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"{sidecar} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ExtractionError(f"{sidecar} must be a JSON object keyed by filename")
    return data


def document_for(
    path: Path,
    title: str,
    sidecar: dict[str, dict],
) -> tuple[Document, list[str]]:
    """Assemble the citation metadata, reporting every field that was guessed."""
    meta = dict(sidecar.get(path.name, {}))
    inferred: list[str] = []

    policy_id = meta.get("policy_id")
    version = meta.get("version")
    if not policy_id or not version:
        guessed_policy, guessed_version = parse_filename(path.stem)
        if not policy_id:
            policy_id = guessed_policy or path.stem.upper()
            inferred.append("policy_id")
        if not version:
            version = guessed_version or "0"
            inferred.append("version")

    doc_type = meta.get("doc_type")
    if not doc_type:
        match = _DOC_TYPE_RE.match(policy_id)
        doc_type = match.group(1).upper() if match else "UNKNOWN"
        inferred.append("doc_type")

    for key in ("library", "effective_date", "last_modified", "owner", "url"):
        if not meta.get(key):
            inferred.append(key)

    document = Document(
        policy_id=policy_id,
        title=meta.get("title") or title,
        version=str(version),
        library=meta.get("library") or "Unknown Library",
        doc_type=doc_type,
        effective_date=meta.get("effective_date") or "",
        last_modified=meta.get("last_modified") or "",
        owner=meta.get("owner") or "",
        url=meta.get("url") or f"file://{path.resolve()}",
        superseded=bool(meta.get("superseded", False)),
        audience=tuple(meta.get("audience", ()) or ()),
    )
    return document, inferred


def chunks_for_document(
    document: Document,
    extracted,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in extracted.sections:
        if not section.text:
            continue
        chunks.extend(
            chunk_section(
                policy_id=document.policy_id,
                version=document.version,
                number=section.number,
                heading=section.heading,
                text=section.text,
                heading_path=section.heading_path,
                audience=document.audience,
                max_chars=max_chars,
                overlap_chars=overlap_chars,
            )
        )
    return chunks


def _chunk_record(chunk: Chunk, document: Document) -> dict:
    return {
        "chunk_id": chunk.chunk_id,
        "section_id": chunk.section_id,
        "policy_id": chunk.policy_id,
        "version": chunk.version,
        "number": chunk.number,
        "heading": chunk.heading,
        "heading_path": list(chunk.heading_path),
        "text": chunk.text,
        "ordinal": chunk.ordinal,
        "total": chunk.total,
        "audience": list(chunk.audience),
        "document": {
            **document.citation(),
            "library": document.library,
            "doc_type": document.doc_type,
            "audience": list(document.audience),
        },
    }


async def ingest(
    sources: list[Path],
    out_dir: Path,
    embedder: Embedder | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    force: bool = False,
) -> IngestResult:
    """Extract, chunk, embed and persist. Unchanged files are reused."""
    embedder = embedder or HashingEmbedder()
    out_dir.mkdir(parents=True, exist_ok=True)

    previous_manifest: dict[str, dict] = {}
    previous_records: dict[str, list[dict]] = {}
    manifest_path = out_dir / MANIFEST_FILE
    chunks_path = out_dir / CHUNKS_FILE
    if not force and manifest_path.exists() and chunks_path.exists():
        previous_manifest = json.loads(manifest_path.read_text()).get("sources", {})
        for record in json.loads(chunks_path.read_text()).get("chunks", []):
            previous_records.setdefault(record.get("source", ""), []).append(record)

    reports: list[SourceReport] = []
    records: list[dict] = []
    manifest: dict[str, dict] = {}

    for path in sources:
        key = str(path)
        try:
            digest = file_digest(path)
        except OSError as exc:
            reports.append(
                SourceReport(key, "", "", 0, 0, skipped_reason=f"unreadable: {exc}")
            )
            continue

        prior = previous_manifest.get(key)
        if prior and prior.get("digest") == digest and key in previous_records:
            reused = previous_records[key]
            records.extend(reused)
            manifest[key] = prior
            reports.append(
                SourceReport(
                    key,
                    prior.get("policy_id", ""),
                    prior.get("version", ""),
                    prior.get("sections", 0),
                    len(reused),
                    skipped_reason="unchanged",
                )
            )
            continue

        try:
            extracted = extract_docx(path)
        except ExtractionError as exc:
            reports.append(SourceReport(key, "", "", 0, 0, skipped_reason=str(exc)))
            continue

        sidecar = load_sidecar(path.parent)
        document, inferred = document_for(path, extracted.title, sidecar)
        chunks = chunks_for_document(document, extracted, max_chars, overlap_chars)
        for chunk in chunks:
            record = _chunk_record(chunk, document)
            record["source"] = key
            records.append(record)

        manifest[key] = {
            "digest": digest,
            "policy_id": document.policy_id,
            "version": document.version,
            "sections": len(extracted.sections),
            "chunks": len(chunks),
        }
        reports.append(
            SourceReport(
                key,
                document.policy_id,
                document.version,
                len(extracted.sections),
                len(chunks),
                inferred=inferred,
            )
        )

    vectors = await embedder.embed_documents([r["text"] for r in records])
    VectorIndex(
        [r["chunk_id"] for r in records], vectors, embedder.name
    ).save(out_dir / VECTORS_FILE)

    chunks_path.write_text(
        json.dumps({"embedder": embedder.name, "chunks": records}, indent=2)
    )
    manifest_path.write_text(
        json.dumps(
            {"embedder": embedder.name, "is_semantic": embedder.is_semantic,
             "sources": manifest},
            indent=2,
        )
    )

    return IngestResult(
        out_dir=str(out_dir),
        embedder=embedder.name,
        is_semantic=embedder.is_semantic,
        total_chunks=len(records),
        sources=reports,
    )


def _collect(inputs: list[str]) -> list[Path]:
    found: list[Path] = []
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            found.extend(sorted(p for p in path.rglob("*.docx") if not p.name.startswith("~$")))
        elif path.suffix.lower() == ".docx":
            found.append(path)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sharepoint_policy_mcp.ingest",
        description="Extract, chunk and embed .docx policy documents.",
    )
    parser.add_argument("sources", nargs="+", help="Folders or .docx files")
    parser.add_argument("-o", "--out", default="index", help="Output folder")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP_CHARS)
    parser.add_argument("--force", action="store_true", help="Re-embed everything")
    args = parser.parse_args(argv)

    paths = _collect(args.sources)
    if not paths:
        print("No .docx files found.", file=sys.stderr)
        return 2

    result = asyncio.run(
        ingest(
            paths,
            Path(args.out),
            max_chars=args.max_chars,
            overlap_chars=args.overlap,
            force=args.force,
        )
    )

    for report in result.sources:
        if report.skipped_reason == "unchanged":
            print(f"  = {report.path} (unchanged, {report.chunks} chunks)")
        elif report.skipped_reason:
            print(f"  ! {report.path}: {report.skipped_reason}", file=sys.stderr)
        else:
            note = f"  [inferred: {', '.join(report.inferred)}]" if report.inferred else ""
            print(
                f"  + {report.path} -> {report.policy_id} v{report.version}, "
                f"{report.sections} sections, {report.chunks} chunks{note}"
            )

    print(
        f"\n{result.total_chunks} chunks indexed in {result.out_dir} "
        f"using {result.embedder}."
    )
    if not result.is_semantic:
        print(
            "WARNING: this embedder is a lexical test rig, not a semantic model. "
            "Retrieval quality is not representative. Configure a real embedder "
            "before indexing policy anyone will rely on.",
            file=sys.stderr,
        )
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
