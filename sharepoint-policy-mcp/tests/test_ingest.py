"""The ingestion pipeline: provenance, chunking, delta sync and persistence."""

import json

import pytest

from sharepoint_policy_mcp.embedder import HashingEmbedder
from sharepoint_policy_mcp.ingest import (
    CHUNKS_FILE,
    MANIFEST_FILE,
    VECTORS_FILE,
    ingest,
    main,
    parse_filename,
)
from sharepoint_policy_mcp.vectors import VectorIndex

FULL_META = {
    "BSA-001 Program Policy v4.2.docx": {
        "policy_id": "BSA-001",
        "title": "BSA/AML Compliance Program Policy",
        "version": "4.2",
        "library": "BSA Policies",
        "doc_type": "BSA",
        "effective_date": "2026-07-01",
        "last_modified": "2026-06-18",
        "owner": "BSA Officer",
        "url": "https://contoso.sharepoint.com/sites/aml/BSA-001.docx",
    }
}


# -- filename inference --------------------------------------------------


@pytest.mark.parametrize(
    "stem,expected",
    [
        ("BSA-001 Program Policy v4.2", ("BSA-001", "4.2")),
        ("qa-014 Alert QA v2.1", ("QA-014", "2.1")),
        ("QC-9 Review v1", ("QC-9", "1")),
    ],
)
def test_filenames_that_follow_the_convention_are_parsed(stem, expected):
    assert parse_filename(stem) == expected


@pytest.mark.parametrize("stem", ["Policy final FINAL", "BSA-001 Program Policy", "v4.2"])
def test_filenames_that_do_not_are_left_alone(stem):
    assert parse_filename(stem) == (None, None)


# -- provenance ----------------------------------------------------------


async def test_sidecar_metadata_populates_the_citation(policy_docx, sidecar, tmp_path):
    sidecar(FULL_META)
    result = await ingest([policy_docx], tmp_path / "out")

    assert result.sources[0].inferred == []
    records = json.loads((tmp_path / "out" / CHUNKS_FILE).read_text())["chunks"]
    citation = records[0]["document"]
    assert citation["policy_id"] == "BSA-001"
    assert citation["version"] == "4.2"
    assert citation["effective_date"] == "2026-07-01"
    assert citation["url"].startswith("https://")


async def test_every_guessed_field_is_reported_not_quietly_assumed(policy_docx, tmp_path):
    # A citation whose version was inferred from a filename is a citation that
    # can be wrong in the one field an examiner will check.
    result = await ingest([policy_docx], tmp_path / "out")
    report = result.sources[0]
    assert report.policy_id == "BSA-001"  # recovered from the filename
    assert report.version == "4.2"
    assert {"library", "effective_date", "owner", "url"} <= set(report.inferred)


async def test_an_unparseable_filename_still_ingests_with_everything_flagged(
    make_docx, tmp_path
):
    path = make_docx("Policy FINAL draft.docx", "Some Policy", [("1", "1.0 A"), ("p", "body")])
    result = await ingest([path], tmp_path / "out")
    report = result.sources[0]
    assert report.chunks == 1
    assert "policy_id" in report.inferred
    assert "version" in report.inferred


# -- chunking and vectors ------------------------------------------------


async def test_sections_become_chunks_with_their_ancestry(policy_docx, sidecar, tmp_path):
    sidecar(FULL_META)
    await ingest([policy_docx], tmp_path / "out")
    records = json.loads((tmp_path / "out" / CHUNKS_FILE).read_text())["chunks"]

    by_number = {r["number"]: r for r in records}
    assert set(by_number) == {"1.0", "5.0", "5.1"}
    assert by_number["5.1"]["heading_path"][-1] == "5.1 SAR Filing Deadlines"
    assert by_number["5.1"]["chunk_id"] == "BSA-001@4.2#5.1"


async def test_a_long_section_produces_several_chunks(make_docx, tmp_path):
    body = "This is a sentence of policy text that repeats. " * 80
    path = make_docx("LNG-001 Long v1.0.docx", "Long", [("1", "1.0 Big"), ("p", body)])
    await ingest([path], tmp_path / "out", max_chars=600)
    records = json.loads((tmp_path / "out" / CHUNKS_FILE).read_text())["chunks"]
    assert len(records) > 1
    assert {r["section_id"] for r in records} == {"LNG-001@1.0#1.0"}
    assert [r["chunk_id"] for r in records] == [
        f"LNG-001@1.0#1.0/{i}" for i in range(len(records))
    ]


async def test_the_vector_index_covers_every_chunk(policy_docx, sidecar, tmp_path):
    sidecar(FULL_META)
    out = tmp_path / "out"
    result = await ingest([policy_docx], out)

    index = VectorIndex.load(out / VECTORS_FILE, expect_embedder="hashing-512")
    assert len(index) == result.total_chunks
    records = json.loads((out / CHUNKS_FILE).read_text())["chunks"]
    assert index.chunk_ids == [r["chunk_id"] for r in records]


async def test_the_embedder_name_is_persisted_for_later_validation(policy_docx, tmp_path):
    out = tmp_path / "out"
    await ingest([policy_docx], out, embedder=HashingEmbedder(64))
    manifest = json.loads((out / MANIFEST_FILE).read_text())
    assert manifest["embedder"] == "hashing-64"
    assert manifest["is_semantic"] is False


# -- delta sync ----------------------------------------------------------


async def test_an_unchanged_file_is_reused_on_the_second_run(policy_docx, tmp_path):
    out = tmp_path / "out"
    first = await ingest([policy_docx], out)
    second = await ingest([policy_docx], out)

    assert first.sources[0].skipped_reason is None
    assert second.sources[0].skipped_reason == "unchanged"
    assert second.total_chunks == first.total_chunks


async def test_an_edited_file_is_re_ingested(policy_docx, make_docx, tmp_path):
    out = tmp_path / "out"
    await ingest([policy_docx], out)

    make_docx(
        policy_docx.name,
        "BSA/AML Compliance Program Policy",
        [("1", "1.0 Purpose"), ("p", "Rewritten text entirely.")],
        directory=policy_docx.parent,
    )
    second = await ingest([policy_docx], out)

    assert second.sources[0].skipped_reason is None
    records = json.loads((out / CHUNKS_FILE).read_text())["chunks"]
    assert any("Rewritten text" in r["text"] for r in records)
    assert not any("120 calendar days" in r["text"] for r in records)


async def test_force_re_ingests_everything(policy_docx, tmp_path):
    out = tmp_path / "out"
    await ingest([policy_docx], out)
    forced = await ingest([policy_docx], out, force=True)
    assert forced.sources[0].skipped_reason is None


async def test_a_broken_file_is_reported_and_the_rest_still_index(
    policy_docx, tmp_path
):
    broken = policy_docx.parent / "BAD-001 Broken v1.0.docx"
    broken.write_text("not a Word file")
    result = await ingest([policy_docx, broken], tmp_path / "out")

    assert len(result.failed) == 1
    assert "could not be opened" in result.failed[0].skipped_reason
    assert result.total_chunks > 0  # the good document still made it


# -- CLI -----------------------------------------------------------------


def test_cli_indexes_a_folder(policy_docx, tmp_path, capsys):
    code = main([str(policy_docx.parent), "-o", str(tmp_path / "cli-out")])
    assert code == 0
    assert (tmp_path / "cli-out" / VECTORS_FILE).exists()
    out = capsys.readouterr()
    assert "chunks indexed" in out.out
    # The warning is the point: nobody should mistake the test rig for
    # retrieval quality.
    assert "not a semantic model" in out.err


def test_cli_reports_when_nothing_was_found(tmp_path, capsys):
    assert main([str(tmp_path), "-o", str(tmp_path / "out")]) == 2
    assert "No .docx files found" in capsys.readouterr().err


def test_cli_exits_nonzero_when_a_file_failed(policy_docx, tmp_path):
    (policy_docx.parent / "BAD-002 Broken v1.0.docx").write_text("nope")
    assert main([str(policy_docx.parent), "-o", str(tmp_path / "out")]) == 1
