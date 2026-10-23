"""Lexical ranking over policy sections: BM25 with a heading boost.

This is the lexical half of the hybrid retrieval the design calls for. The
dense half -- embeddings over the same sections -- arrives with the real
ingestion pipeline; until then this is what ranks, and it is honest about
being only half.

Lexical-first is not a stopgap chosen at random. BSA language is formulaic and
analysts quote it almost verbatim ("continuing activity", "within 30 calendar
days"), which is exactly the case BM25 handles well and dense retrieval
blurs. What it cannot do is match a question that shares no words with the
answer, and that is what the embeddings are for.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Iterable

from .models import Document, Hit, Section

# BM25 parameters. k1 controls how fast term frequency saturates, b how hard
# long documents are penalised. These are the usual defaults and there is no
# reason to tune them before there is an evaluation set to tune against.
K1 = 1.5
B = 0.75

# A heading is a strong signal in a policy document: "SAR Filing Deadlines" is
# a better answer to a deadline question than a body paragraph that mentions
# deadlines in passing. Implemented as repetition of the heading tokens, which
# is the cheap form of a field boost.
HEADING_REPEAT = 3

_STOPWORDS = frozenset(
    """
    a an and are as at be been but by can do does for from has have how i if in
    into is it its may must not of on or our shall should so than that the their
    them then there these this to was we were what when where which who why will
    with you your
    """.split()
)

# Domain aliases, expanded on the query side only so that document statistics
# stay untouched. An analyst types "SAR deadline"; the policy says "suspicious
# activity report". Without this the lexical half misses, and in a compliance
# tool a miss is not a neutral event -- it reads as "the policy is silent".
_ALIASES: dict[str, tuple[str, ...]] = {
    "sar": ("suspicious", "activity", "report"),
    "ctr": ("currency", "transaction", "report"),
    "cdd": ("customer", "due", "diligence"),
    "edd": ("enhanced", "due", "diligence"),
    "kyc": ("know", "your", "customer"),
    "bsa": ("bank", "secrecy", "act"),
    "qa": ("quality", "assurance"),
    "qc": ("quality", "control"),
    "pep": ("politically", "exposed", "person"),
    "ofac": ("sanctions", "screening"),
    "fincen": ("financial", "crimes", "enforcement", "network"),
    "deadline": ("days", "timeline", "filing"),
    "escalate": ("escalation",),
}

# "314(a)" -> "314a", so the subsection letter survives tokenisation instead of
# being dropped as a one-character token. The difference between 314(a) and
# 314(b) is the difference between answering a law-enforcement request and
# sharing information with another bank.
_SUBSECTION_RE = re.compile(r"(\d+)\(([a-zA-Z])\)")
# Thousands separators inside numbers: "10,000" -> "10000".
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}\b)")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase, normalise policy-shaped numbers, split, drop stopwords."""
    if not text:
        return []
    lowered = _SUBSECTION_RE.sub(r"\1\2", text.lower())
    lowered = _THOUSANDS_RE.sub("", lowered)
    return [
        token
        for token in _TOKEN_RE.findall(lowered)
        if len(token) > 1 and token not in _STOPWORDS
    ]


def expand_query(tokens: Iterable[str]) -> list[str]:
    """Add domain synonyms for acronyms the policy text spells out in full."""
    out: list[str] = []
    for token in tokens:
        out.append(token)
        out.extend(_ALIASES.get(token, ()))
    return out


class PolicyIndex:
    """An in-memory BM25 index over policy sections.

    Corpus statistics are computed over every section, including ones the
    caller may not read. That is deliberate: idf should not shift depending on
    who is asking, or two analysts get different rankings for the same
    question and neither can reproduce the other's result. Entitlement
    filtering happens on candidate selection, before anything is returned.
    """

    def __init__(self, pairs: Iterable[tuple[Section, Document]]) -> None:
        self._sections: list[Section] = []
        self._documents: list[Document] = []
        self._term_freqs: list[Counter[str]] = []
        self._lengths: list[int] = []
        document_freq: Counter[str] = Counter()

        for section, document in pairs:
            tokens = tokenize(section.text) + tokenize(section.heading) * HEADING_REPEAT
            freqs = Counter(tokens)
            self._sections.append(section)
            self._documents.append(document)
            self._term_freqs.append(freqs)
            self._lengths.append(len(tokens))
            document_freq.update(freqs.keys())

        self._document_freq = document_freq
        self._count = len(self._sections)
        self._avg_length = (sum(self._lengths) / self._count) if self._count else 0.0

    def __len__(self) -> int:
        return self._count

    def _idf(self, term: str) -> float:
        df = self._document_freq.get(term, 0)
        if df == 0:
            return 0.0
        return math.log(1 + (self._count - df + 0.5) / (df + 0.5))

    def search(
        self,
        query: str,
        where: Callable[[Section, Document], bool] | None = None,
        limit: int | None = None,
    ) -> list[Hit]:
        """Rank sections against `query`, keeping only those `where` admits.

        `limit` of None returns every section that scored above zero. Callers
        that still have filtering to do -- entitlement trimming, say -- need
        the full ranked list, because a cap applied before that filter silently
        drops results the caller was entitled to see.
        """
        terms = expand_query(tokenize(query))
        if not terms or self._count == 0:
            return []

        # Each distinct term contributes once; repeating a word in the question
        # should not weight it twice.
        unique_terms = list(dict.fromkeys(terms))
        idfs = {term: self._idf(term) for term in unique_terms}

        hits: list[Hit] = []
        for i in range(self._count):
            section = self._sections[i]
            document = self._documents[i]
            if where is not None and not where(section, document):
                continue

            freqs = self._term_freqs[i]
            length = self._lengths[i] or 1
            score = 0.0
            matched: list[str] = []
            for term in unique_terms:
                tf = freqs.get(term, 0)
                if tf == 0:
                    continue
                idf = idfs[term]
                if idf <= 0.0:
                    continue
                denominator = tf + K1 * (1 - B + B * length / (self._avg_length or 1))
                score += idf * (tf * (K1 + 1)) / denominator
                matched.append(term)

            if score > 0.0:
                hits.append(
                    Hit(
                        section=section,
                        document=document,
                        score=round(score, 4),
                        matched_terms=tuple(matched),
                    )
                )

        # Ties broken by section id so that repeating a query gives the same
        # order. An assistant that reorders its citations between identical
        # questions is one nobody trusts twice.
        hits.sort(key=lambda h: (-h.score, h.section.section_id))
        return hits if limit is None else hits[:limit]
