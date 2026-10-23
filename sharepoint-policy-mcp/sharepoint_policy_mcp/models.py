"""The shapes that move between the store, the ranker and the tools.

A passage that reaches the model without a citation is worse than no passage
at all: it reads as authoritative and cannot be checked. So the citation
fields are part of `Section` itself rather than something the server layer
assembles hopefully at the end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Document:
    """One policy document, at one version."""

    policy_id: str
    title: str
    version: str
    library: str
    doc_type: str  # BSA | QA | QC
    effective_date: str  # ISO date the version took effect
    last_modified: str  # ISO date the file last changed in SharePoint
    owner: str
    url: str
    superseded: bool = False
    # Entitlement groups that may read this document. Empty means anyone with
    # access to the site.
    audience: tuple[str, ...] = ()

    def citation(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "title": self.title,
            "version": self.version,
            "effective_date": self.effective_date,
            "last_modified": self.last_modified,
            "owner": self.owner,
            "url": self.url,
            "superseded": self.superseded,
        }


@dataclass(frozen=True)
class Section:
    """A heading-bounded chunk of a document: the unit we retrieve and cite."""

    section_id: str
    policy_id: str
    number: str  # e.g. "4.2"
    heading: str
    text: str
    audience: tuple[str, ...] = ()


@dataclass(frozen=True)
class Hit:
    """A ranked section, with the score that put it there."""

    section: Section
    document: Document
    score: float
    matched_terms: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Chunk:
    """A retrievable unit: a section, or one piece of a section too long to embed.

    A chunk carries its ancestry. A clause split off the bottom of
    "5.1 SAR Filing Deadlines" must still cite that heading, or the analyst gets
    a deadline with nothing saying which deadline it is.
    """

    chunk_id: str  # "BSA-001@4.2#5.1/1"
    section_id: str
    policy_id: str
    version: str
    number: str
    heading: str
    heading_path: tuple[str, ...]  # document title down to this section
    text: str
    ordinal: int  # 0-based position within the section
    total: int  # how many chunks the section produced
    audience: tuple[str, ...] = ()

    @property
    def is_partial(self) -> bool:
        return self.total > 1

    def as_section(self) -> Section:
        """View this chunk as a Section, for the lexical index.

        The heading carries the ancestry so that heading-boosted scoring sees
        the parent terms too -- a chunk of 5.1 should still match "SAR".
        """
        return Section(
            section_id=self.chunk_id,
            policy_id=self.policy_id,
            number=self.number,
            heading=" ".join(self.heading_path),
            text=self.text,
            audience=self.audience,
        )
