"""Policy stores: an in-memory mock now, a Graph-backed one later.

Both will satisfy the same small read-only surface so the MCP server never
knows which it is talking to. That is what keeps the tool layer testable
without an Entra ID app registration and without network egress -- the same
bargain `servicenow_mcp` makes with its mock instance.
"""

from __future__ import annotations

from typing import Any, Protocol

from .config import ConfigError, Settings
from .corpus import DOCUMENTS, documents_by_key, pairs, version_of
from .embedder import Embedder, HashingEmbedder
from .hybrid import rank_ids, reciprocal_rank_fusion
from .models import Document, Hit, Section
from .search import PolicyIndex
from .vectors import VectorIndex


class PolicyStoreError(RuntimeError):
    """A policy lookup failed in a way the caller should see."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class PolicyStore(Protocol):
    """The read-only surface the MCP tools depend on."""

    async def ping(self) -> dict[str, Any]: ...

    async def list_documents(self, include_superseded: bool) -> list[Document]: ...

    async def search(
        self,
        query: str,
        doc_type: str | None,
        policy_id: str | None,
        include_superseded: bool,
        limit: int,
    ) -> tuple[list[Hit], int]: ...

    async def get_section(
        self, section_id: str
    ) -> tuple[Section, Document] | None: ...

    async def sections_for(
        self, policy_id: str, version: str
    ) -> list[Section] | None: ...

    async def aclose(self) -> None: ...


# --------------------------------------------------------------------------
# Mock store
# --------------------------------------------------------------------------


class MockPolicyStore:
    """Serves the synthetic corpus in `corpus.py`, with the real guardrails.

    The entitlement and allowlist checks here are not mock behaviour standing
    in for the real thing -- they are the real checks, running over mock data.
    A control that only exists in the production path is a control nobody has
    ever seen fail.
    """

    def __init__(self, settings: Settings, embedder: Embedder | None = None) -> None:
        self._settings = settings
        self._pairs = pairs()
        self._index = PolicyIndex(self._pairs)
        self._by_key = documents_by_key()
        self._by_id = {section.section_id: (section, doc) for section, doc in self._pairs}
        self._embedder = embedder or HashingEmbedder(settings.embedding_dimensions)
        self._vectors: VectorIndex | None = None

    async def _ensure_vectors(self) -> VectorIndex:
        """Embed the corpus on first hybrid search, not at construction.

        Importing this module must stay free of work: the server builds its
        backend lazily so that `claude mcp list` does not pay for an index it
        may never query.
        """
        if self._vectors is None:
            texts = [section.text for section, _ in self._pairs]
            matrix = await self._embedder.embed_documents(texts)
            self._vectors = VectorIndex(
                [section.section_id for section, _ in self._pairs],
                matrix,
                self._embedder.name,
            )
        return self._vectors

    # -- guardrails ------------------------------------------------------

    def _visible(self, document: Document) -> bool:
        """Whether the caller may see this document at all."""
        if not self._settings.library_allowed(document.library):
            return False
        return self._settings.may_read(document.audience)

    def _section_visible(self, section: Section, document: Document) -> bool:
        if not self._visible(document):
            return False
        return self._settings.may_read(section.audience)

    # -- surface ---------------------------------------------------------

    async def ping(self) -> dict[str, Any]:
        visible = [d for d in DOCUMENTS if self._visible(d)]
        return {
            "ok": True,
            "backend": "mock",
            "auth_mode": self._settings.auth_mode,
            "site_url": self._settings.site_url,
            "documents_indexed": len(DOCUMENTS),
            "documents_visible": len(visible),
            "sections_indexed": len(self._index),
            "retrieval": self._settings.retrieval,
            "retrieval_detail": (
                f"BM25 fused with {self._embedder.name} by reciprocal rank"
                if self._settings.is_hybrid
                else "BM25 only; set SP_RETRIEVAL=hybrid to fuse in embeddings"
            ),
            "embedder": self._embedder.name,
            "embedder_is_semantic": self._embedder.is_semantic,
            "corpus": "SYNTHETIC -- illustrative policy text, not your institution's",
        }

    async def list_documents(self, include_superseded: bool) -> list[Document]:
        return [
            d
            for d in DOCUMENTS
            if self._visible(d) and (include_superseded or not d.superseded)
        ]

    async def search(
        self,
        query: str,
        doc_type: str | None,
        policy_id: str | None,
        include_superseded: bool,
        limit: int,
    ) -> tuple[list[Hit], int]:
        wanted_type = (doc_type or "").strip().upper() or None
        wanted_policy = (policy_id or "").strip().upper() or None

        def admits(section: Section, document: Document) -> bool:
            if wanted_type and document.doc_type.upper() != wanted_type:
                return False
            if wanted_policy and document.policy_id.upper() != wanted_policy:
                return False
            return include_superseded or not document.superseded

        # Entitlement is applied after scoring, not inside `admits`, so that
        # the cap does not silently drop results the caller was entitled to
        # see. Readable hits below the cut line are promoted to backfill the
        # page.
        ranked = self._index.search(query, where=admits, limit=None)
        if self._settings.is_hybrid:
            ranked = await self._fuse(query, ranked, admits)
        readable = [h for h in ranked if self._section_visible(h.section, h.document)]

        # `withheld` counts only unreadable sections that would have appeared
        # in this page of results. Counting every unreadable section that
        # shares a word with the question would raise the flag on nearly every
        # search, and a warning that fires constantly is one nobody reads.
        # Counted rather than silently dropped, because "no policy covers
        # this" and "a policy covers this and you may not read it" are
        # different answers, and conflating them misleads the analyst.
        withheld = sum(
            1
            for hit in ranked[:limit]
            if not self._section_visible(hit.section, hit.document)
        )
        return readable[:limit], withheld

    async def _fuse(
        self,
        query: str,
        lexical: list[Hit],
        admits,
    ) -> list[Hit]:
        """Combine the lexical ranking with the dense one by rank, not score.

        The dense side can surface a section the lexical side scored at zero,
        so the fused list is rebuilt from ids rather than reordered in place.
        Scores from the two retrievers are never added -- see hybrid.py.
        """
        vectors = await self._ensure_vectors()
        query_vector = await self._embedder.embed_query(query)

        dense: list[str] = []
        for section_id in rank_ids(vectors.search(query_vector)):
            found = self._by_id.get(section_id)
            # The hard filters (doc_type, policy_id, superseded) are applied
            # to the dense side too; entitlement is still handled after
            # fusion, so `withheld` keeps counting the page it would have.
            if found is not None and admits(found[0], found[1]):
                dense.append(section_id)

        lexical_by_id = {hit.section.section_id: hit for hit in lexical}
        fused = reciprocal_rank_fusion(
            {"lexical": [h.section.section_id for h in lexical], "dense": dense}
        )

        out: list[Hit] = []
        for entry in fused:
            prior = lexical_by_id.get(entry.doc_id)
            if prior is not None:
                out.append(
                    Hit(
                        section=prior.section,
                        document=prior.document,
                        score=entry.score,
                        matched_terms=prior.matched_terms,
                    )
                )
                continue
            found = self._by_id.get(entry.doc_id)
            if found is None:
                continue
            section, document = found
            # Retrieved on the dense side alone: no lexical terms matched, and
            # saying so is more useful than an empty tuple that looks like a bug.
            out.append(
                Hit(section=section, document=document, score=entry.score, matched_terms=())
            )
        return out

    async def get_section(self, section_id: str) -> tuple[Section, Document] | None:
        for section, document in pairs():
            if section.section_id != section_id:
                continue
            if not self._section_visible(section, document):
                raise PolicyStoreError(
                    f"Section {section_id!r} exists but is not readable by groups "
                    f"{', '.join(self._settings.user_groups)}.",
                    status=403,
                )
            return section, document
        return None

    async def sections_for(self, policy_id: str, version: str) -> list[Section] | None:
        key = (policy_id.strip().upper(), version.strip())
        document = self._by_key.get(key)
        if document is None:
            return None
        if not self._visible(document):
            raise PolicyStoreError(
                f"Policy {policy_id} version {version} is not readable by groups "
                f"{', '.join(self._settings.user_groups)}.",
                status=403,
            )
        return [
            section
            for section, doc in pairs()
            if doc.policy_id == document.policy_id
            and version_of(section.section_id) == document.version
            and self._settings.may_read(section.audience)
        ]

    async def aclose(self) -> None:
        return None


# --------------------------------------------------------------------------
# Graph store -- not built yet
# --------------------------------------------------------------------------


def graph_store_unavailable() -> ConfigError:
    """The error raised when someone sets SP_AUTH_MODE=graph today.

    Kept as a function rather than a bare string so the message lives in one
    place, and so the shape of the real store is documented where someone
    looking for it will find it.
    """
    return ConfigError(
        "SP_AUTH_MODE=graph is not implemented in this version. The Graph-backed "
        "store needs the ingestion pipeline (download, section-aware chunking, "
        "embedding, delta sync) and per-user entitlement trimming before it is "
        "safe to point at a real site. Run with SP_AUTH_MODE=mock for now."
    )
