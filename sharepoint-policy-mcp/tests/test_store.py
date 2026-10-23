"""The mock store, and the guardrails that run over it.

The entitlement and allowlist checks are not mock behaviour standing in for
the real thing -- they are the real checks, running over mock data. These
tests are what stop them regressing before the Graph backend exists.
"""

import pytest

from sharepoint_policy_mcp.config import Settings
from sharepoint_policy_mcp.store import MockPolicyStore, PolicyStoreError


def store(**overrides) -> MockPolicyStore:
    base = {
        "site_url": "https://mock.sharepoint.com/sites/aml-policy",
        "auth_mode": "mock",
    }
    base.update(overrides)
    return MockPolicyStore(Settings(**base))


async def test_ping_reports_the_mock_corpus():
    out = await store().ping()
    assert out["ok"] is True
    assert out["backend"] == "mock"
    assert out["sections_indexed"] > 0
    assert "SYNTHETIC" in out["corpus"]


async def test_current_documents_exclude_superseded_by_default():
    documents = await store().list_documents(include_superseded=False)
    assert documents
    assert all(not d.superseded for d in documents)


async def test_superseded_documents_can_be_requested():
    documents = await store().list_documents(include_superseded=True)
    assert any(d.superseded for d in documents)


async def test_analyst_cannot_see_the_restricted_document():
    documents = await store().list_documents(include_superseded=True)
    assert "QC-022" not in {d.policy_id for d in documents}


async def test_manager_can_see_the_restricted_document():
    documents = await store(user_groups=("aml-manager",)).list_documents(True)
    assert "QC-022" in {d.policy_id for d in documents}


async def test_library_allowlist_removes_a_whole_library():
    narrowed = store(allowed_libraries=("BSA Policies",))
    documents = await narrowed.list_documents(include_superseded=True)
    assert {d.library for d in documents} == {"BSA Policies"}


async def test_search_counts_withheld_sections_rather_than_hiding_them():
    hits, withheld = await store().search(
        "law enforcement subpoena grand jury", None, None, False, 5
    )
    assert withheld > 0
    assert all(h.document.policy_id != "QC-022" for h in hits)


async def test_the_same_search_as_a_manager_returns_the_withheld_sections():
    hits, withheld = await store(user_groups=("aml-manager",)).search(
        "law enforcement subpoena grand jury", None, None, False, 5
    )
    assert withheld == 0
    assert any(h.document.policy_id == "QC-022" for h in hits)


async def test_withheld_counts_only_sections_that_matched_the_question():
    # A query with nothing to do with the restricted document must not report
    # it as withheld, or every search reads as "there is something you cannot
    # see" and the signal becomes noise.
    _, withheld = await store().search(
        "currency transaction report threshold", None, None, False, 5
    )
    assert withheld == 0


async def test_doc_type_filter_narrows_results():
    hits, _ = await store().search("quality", "QA", None, False, 10)
    assert hits
    assert {h.document.doc_type for h in hits} == {"QA"}


async def test_policy_id_filter_narrows_results():
    hits, _ = await store().search("filing", None, "QC-009", False, 10)
    assert hits
    assert {h.document.policy_id for h in hits} == {"QC-009"}


async def test_superseded_sections_are_excluded_from_search_by_default():
    hits, _ = await store().search("SAR filing deadline", None, None, False, 10)
    assert all(not h.document.superseded for h in hits)


async def test_limit_applies_after_entitlement_filtering():
    hits, _ = await store().search("suspicious activity report", None, None, False, 2)
    assert len(hits) == 2


async def test_get_section_returns_the_section_and_its_document():
    found = await store().get_section("BSA-001@4.2#5.1")
    assert found is not None
    section, document = found
    assert section.heading == "SAR Filing Deadlines"
    assert document.version == "4.2"


async def test_get_section_returns_none_for_an_unknown_id():
    assert await store().get_section("BSA-001@9.9#1.0") is None


async def test_get_section_refuses_a_restricted_section():
    with pytest.raises(PolicyStoreError) as excinfo:
        await store().get_section("QC-022@1.2#1.0")
    assert excinfo.value.status == 403


async def test_sections_for_returns_a_whole_version():
    sections = await store().sections_for("BSA-001", "4.2")
    assert sections
    assert {s.number for s in sections} >= {"1.0", "5.1", "10.0"}


async def test_sections_for_is_case_insensitive_on_policy_id():
    assert await store().sections_for("bsa-001", "4.2")


async def test_sections_for_returns_none_for_an_unknown_version():
    assert await store().sections_for("BSA-001", "0.1") is None


async def test_sections_for_refuses_a_restricted_policy():
    with pytest.raises(PolicyStoreError):
        await store().sections_for("QC-022", "1.2")


async def test_readable_results_backfill_the_page_when_sections_are_withheld():
    # A withheld section should cost the analyst that result, not the slot:
    # the next readable section is promoted into the page.
    query = "law enforcement contact about a filed report"
    analyst, withheld = await store().search(query, None, None, False, 3)
    manager, _ = await store(user_groups=("aml-manager",)).search(
        query, None, None, False, 3
    )

    assert withheld == 1
    assert manager[0].document.policy_id == "QC-022"
    # Both get a full page: the analyst's third slot is a section the manager's
    # page pushed off the bottom, not an empty row.
    assert len(analyst) == len(manager) == 3
    assert [h.section.section_id for h in analyst] == [
        h.section.section_id for h in manager[1:]
    ] + [analyst[-1].section.section_id]
    assert analyst[-1].section.section_id not in {
        h.section.section_id for h in manager
    }
