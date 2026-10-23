"""Tokenisation and BM25 ranking over the synthetic corpus."""

from sharepoint_policy_mcp.corpus import pairs
from sharepoint_policy_mcp.search import PolicyIndex, expand_query, tokenize


def index() -> PolicyIndex:
    return PolicyIndex(pairs())


# -- tokenisation --------------------------------------------------------


def test_stopwords_and_single_characters_are_dropped():
    assert tokenize("the report is in a file") == ["report", "file"]


def test_subsection_letters_survive_tokenisation():
    # 314(a) is a law-enforcement request; 314(b) is voluntary information
    # sharing. Collapsing both to "314" makes the two indistinguishable.
    assert "314a" in tokenize("a 314(a) request from FinCEN")
    assert "314b" in tokenize("314(b) information sharing")
    assert tokenize("314(a)") != tokenize("314(b)")


def test_thousands_separators_are_normalised():
    assert "10000" in tokenize("more than $10,000 in currency")


def test_tokenize_handles_empty_input():
    assert tokenize("") == []
    assert tokenize("   ") == []


def test_query_expansion_adds_acronym_expansions():
    expanded = expand_query(["sar"])
    assert expanded[0] == "sar"
    assert {"suspicious", "activity", "report"} <= set(expanded)


def test_query_expansion_leaves_unknown_terms_alone():
    assert expand_query(["structuring"]) == ["structuring"]


# -- ranking -------------------------------------------------------------


def test_deadline_question_ranks_the_deadline_section_first():
    # Superseded versions are excluded the way the store excludes them. They
    # are left in the index on purpose -- BM25 length normalisation favours
    # the shorter v4.1 wording of this very section, which is exactly why
    # version filtering belongs in the store and not in the ranker.
    hits = index().search(
        "how many days to file a SAR after initial detection",
        where=lambda section, document: not document.superseded,
    )
    assert hits[0].section.section_id == "BSA-001@4.2#5.1"
    assert "30 calendar days" in hits[0].section.text


def test_superseded_sections_are_reachable_when_not_filtered_out():
    hits = index().search("SAR filing deadline initial detection")
    assert any(h.document.superseded for h in hits)


def test_ctr_threshold_question_finds_the_ctr_section():
    hits = index().search("what is the currency transaction report threshold")
    assert hits[0].section.heading == "Currency Transaction Reporting"


def test_acronym_only_query_still_matches_the_spelled_out_policy_text():
    # The corpus never writes "CDD"; it writes "customer due diligence".
    # Without query expansion this returns nothing.
    hits = index().search("CDD requirements")
    assert hits, "acronym query returned nothing; expansion is not working"
    assert any("Due Diligence" in h.section.heading for h in hits[:3])


def test_heading_terms_outrank_passing_body_mentions():
    hits = index().search("independent testing")
    assert hits[0].section.heading == "Independent Testing"


def test_nonsense_query_returns_nothing():
    assert index().search("zzzzxqv unrelated gibberish") == []


def test_empty_query_returns_nothing():
    assert index().search("") == []


def test_limit_is_respected_and_none_means_everything():
    idx = index()
    capped = idx.search("suspicious activity report", limit=3)
    uncapped = idx.search("suspicious activity report", limit=None)
    assert len(capped) == 3
    assert len(uncapped) > 3
    assert [h.section_id for h in (hit.section for hit in capped)] == [
        h.section_id for h in (hit.section for hit in uncapped[:3])
    ]


def test_scores_are_ordered_descending():
    hits = index().search("quality control review of a filing")
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_ranking_is_deterministic():
    # An assistant that reorders its citations between identical questions is
    # one nobody trusts twice.
    first = [h.section.section_id for h in index().search("training requirements")]
    second = [h.section.section_id for h in index().search("training requirements")]
    assert first == second


def test_where_predicate_filters_candidates():
    hits = index().search(
        "suspicious activity report",
        where=lambda section, document: document.doc_type == "QC",
    )
    assert hits
    assert {h.document.doc_type for h in hits} == {"QC"}


def test_matched_terms_are_reported():
    hits = index().search("recordkeeping retention five years")
    assert hits
    assert "retention" in hits[0].matched_terms


def test_empty_index_is_safe():
    assert PolicyIndex([]).search("anything") == []
    assert len(PolicyIndex([])) == 0
