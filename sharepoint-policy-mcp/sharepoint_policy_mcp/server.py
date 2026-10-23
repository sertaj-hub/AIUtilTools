"""The MCP server: AML policy reads exposed as tools.

Every tool here is read-only and every passage it returns carries a citation.
That second property is the point of the whole server. An analyst who asks
"how long do I have to file?" and gets a confident paragraph with no source
has been given something worse than nothing: an answer that reads as
authoritative, cannot be checked, and will not survive an examiner asking
where it came from.
"""

from __future__ import annotations

import difflib
import logging
import os
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from .config import ConfigError, Settings
from .models import Document, Hit, Section
from .redaction import redact_text
from .store import MockPolicyStore, PolicyStore, PolicyStoreError, graph_store_unavailable

# stderr only: stdout is the MCP transport, and anything printed there
# corrupts the protocol stream. This is the single most common way to break a
# stdio MCP server.
logging.basicConfig(
    level=os.environ.get("SP_LOG_LEVEL", "INFO"),
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("sharepoint_policy_mcp")

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)

DOC_TYPES = ("BSA", "QA", "QC")

mcp = MCPServer(
    name="sharepoint-policy",
    version="0.1.0",
    instructions=(
        "Read-only access to AML policy documents (BSA program policy, QA and QC "
        "procedures) held in SharePoint. Call sp_list_sources first to see which "
        "policies are available and at which version. Use sp_search_policy to find "
        "relevant passages, then sp_get_section when a passage is truncated or you "
        "need the surrounding clause. "
        "Always quote the policy_id, version and section number from the citation "
        "when answering; never state a policy requirement without one. If the "
        "search returns nothing, say the policy appears silent rather than "
        "answering from general knowledge of BSA requirements -- the institution's "
        "policy may be stricter than the regulation."
    ),
)


class _Backend:
    """Lazily built so that importing this module never needs credentials."""

    def __init__(self) -> None:
        self._settings: Settings | None = None
        self._store: PolicyStore | None = None

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = Settings.from_env()
        return self._settings

    @property
    def store(self) -> PolicyStore:
        if self._store is None:
            settings = self.settings
            if not settings.is_mock:
                raise graph_store_unavailable()
            log.info("Starting with the mock corpus; no network calls will be made.")
            self._store = MockPolicyStore(settings)
        return self._store


backend = _Backend()


def _require_query(query: str) -> str:
    value = (query or "").strip()
    if not value:
        raise ToolError("query is required")
    if len(value) > 500:
        raise ToolError("query must be 500 characters or fewer")
    return value


def _require_doc_type(doc_type: str | None) -> str | None:
    if doc_type is None or not doc_type.strip():
        return None
    value = doc_type.strip().upper()
    if value not in DOC_TYPES:
        raise ToolError(
            f"doc_type must be one of {', '.join(DOC_TYPES)}, got {doc_type!r}"
        )
    return value


def _passage(text: str, settings: Settings) -> tuple[str, bool]:
    """Mask sensitive values, then clip to the configured passage budget."""
    masked = redact_text(text, settings.redact)
    if len(masked) <= settings.max_passage_chars:
        return masked, False
    # Clip on a word boundary so the passage does not end mid-term; the caller
    # gets the section id and can fetch the rest with sp_get_section.
    clipped = masked[: settings.max_passage_chars].rsplit(" ", 1)[0]
    return clipped + " ...", True


def _hit_payload(hit: Hit, settings: Settings) -> dict[str, Any]:
    text, truncated = _passage(hit.section.text, settings)
    return {
        "section_id": hit.section.section_id,
        "section": f"{hit.section.number} {hit.section.heading}",
        "text": text,
        "text_truncated": truncated,
        "score": hit.score,
        "matched_terms": list(hit.matched_terms),
        "citation": hit.document.citation(),
    }


def _document_payload(document: Document) -> dict[str, Any]:
    payload = document.citation()
    payload["library"] = document.library
    payload["doc_type"] = document.doc_type
    return payload


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Check connectivity and report how this server is configured, including "
        "which retrieval method is active. Use this first when something is not "
        "working, or when you need to know whether you are reading real policy or "
        "the synthetic test corpus."
    ),
    annotations=READ_ONLY,
)
async def sp_ping() -> dict[str, Any]:
    try:
        return await backend.store.ping()
    except ConfigError as exc:
        return {"ok": False, "error": f"Configuration problem: {exc}"}
    except PolicyStoreError as exc:
        return {"ok": False, "error": str(exc), "status": exc.status}


@mcp.tool(
    description=(
        "List the policy documents this server can read, with their version, "
        "effective date, owner and SharePoint URL. Set include_superseded to see "
        "archived versions as well as current ones."
    ),
    annotations=READ_ONLY,
)
async def sp_list_sources(include_superseded: bool = False) -> dict[str, Any]:
    settings = backend.settings
    try:
        documents = await backend.store.list_documents(include_superseded)
    except PolicyStoreError as exc:
        raise ToolError(f"Listing policy documents failed: {exc}") from exc

    return {
        "site_url": settings.site_url,
        "allowed_libraries": list(settings.allowed_libraries),
        "caller_groups": list(settings.user_groups),
        "count": len(documents),
        "documents": [_document_payload(d) for d in documents],
    }


@mcp.tool(
    description=(
        "Search AML policy for passages relevant to a question and return them "
        "with citations. Ask in the analyst's own words -- 'how long do I have to "
        "file a continuing activity SAR' works better than a keyword list. "
        "Narrow with doc_type (BSA, QA or QC) or policy_id when you know where the "
        "answer lives. Superseded versions are excluded unless you ask for them."
    ),
    annotations=READ_ONLY,
)
async def sp_search_policy(
    query: str,
    doc_type: str | None = None,
    policy_id: str | None = None,
    include_superseded: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    settings = backend.settings
    text = _require_query(query)
    wanted_type = _require_doc_type(doc_type)
    capped = settings.clamp_limit(limit)

    try:
        hits, withheld = await backend.store.search(
            text, wanted_type, policy_id, include_superseded, capped
        )
    except PolicyStoreError as exc:
        raise ToolError(f"Policy search failed: {exc}") from exc

    payload: dict[str, Any] = {
        "query": text,
        "doc_type": wanted_type,
        "policy_id": policy_id,
        "include_superseded": include_superseded,
        "count": len(hits),
        "limit": capped,
        "truncated": len(hits) == capped,
        "retrieval": "lexical (BM25)",
        "results": [_hit_payload(h, settings) for h in hits],
    }
    if withheld:
        # Surfaced rather than swallowed, so the analyst can ask the right
        # person instead of concluding the policy is silent.
        payload["withheld_by_entitlement"] = withheld
        payload["withheld_note"] = (
            f"{withheld} matching section(s) exist in policies your groups "
            f"({', '.join(settings.user_groups)}) may not read. Ask the document "
            "owner or the BSA Officer for access."
        )
    if not hits:
        payload["note"] = (
            "No policy passage matched. Say so rather than answering from general "
            "BSA knowledge: the institution's policy may differ from the regulation."
        )
    return payload


@mcp.tool(
    description=(
        "Fetch one policy section in full by its section_id, as returned in a "
        "search result. Use this when a search passage was truncated, or when you "
        "need the exact wording of a clause to quote it."
    ),
    annotations=READ_ONLY,
)
async def sp_get_section(section_id: str) -> dict[str, Any]:
    settings = backend.settings
    ident = (section_id or "").strip()
    if not ident:
        raise ToolError("section_id is required")

    try:
        found = await backend.store.get_section(ident)
    except PolicyStoreError as exc:
        raise ToolError(str(exc)) from exc

    if found is None:
        raise ToolError(
            f"No section {ident!r}. section_id looks like 'BSA-001@4.2#5.1'; "
            "call sp_search_policy or sp_list_sources to find a valid one."
        )

    section, document = found
    return {
        "section_id": section.section_id,
        "section": f"{section.number} {section.heading}",
        "text": redact_text(section.text, settings.redact),
        "text_truncated": False,
        "citation": document.citation(),
    }


@mcp.tool(
    description=(
        "Compare two versions of the same policy and report which sections were "
        "added, removed or reworded, with a line diff for the changes. Use this "
        "when an analyst asks what changed in a policy, or when a QC finding turns "
        "on which version was in force at the time of the work."
    ),
    annotations=READ_ONLY,
)
async def sp_policy_diff(
    policy_id: str,
    from_version: str,
    to_version: str,
) -> dict[str, Any]:
    ident = (policy_id or "").strip()
    if not ident:
        raise ToolError("policy_id is required")
    older = (from_version or "").strip()
    newer = (to_version or "").strip()
    if not older or not newer:
        raise ToolError("from_version and to_version are both required")
    if older == newer:
        raise ToolError("from_version and to_version are the same")

    try:
        before = await backend.store.sections_for(ident, older)
        after = await backend.store.sections_for(ident, newer)
    except PolicyStoreError as exc:
        raise ToolError(str(exc)) from exc

    if before is None:
        raise ToolError(f"No version {older!r} of policy {ident!r}")
    if after is None:
        raise ToolError(f"No version {newer!r} of policy {ident!r}")

    before_by_number: dict[str, Section] = {s.number: s for s in before}
    after_by_number: dict[str, Section] = {s.number: s for s in after}

    added = [
        {"number": n, "heading": after_by_number[n].heading}
        for n in sorted(set(after_by_number) - set(before_by_number))
    ]
    removed = [
        {"number": n, "heading": before_by_number[n].heading}
        for n in sorted(set(before_by_number) - set(after_by_number))
    ]

    modified: list[dict[str, Any]] = []
    unchanged = 0
    for number in sorted(set(before_by_number) & set(after_by_number)):
        old_section = before_by_number[number]
        new_section = after_by_number[number]
        if old_section.text == new_section.text and old_section.heading == new_section.heading:
            unchanged += 1
            continue
        diff = difflib.unified_diff(
            old_section.text.split(". "),
            new_section.text.split(". "),
            fromfile=f"{ident} v{older} s{number}",
            tofile=f"{ident} v{newer} s{number}",
            lineterm="",
            n=0,
        )
        modified.append(
            {
                "number": number,
                "heading": new_section.heading,
                "heading_changed": old_section.heading != new_section.heading,
                "diff": "\n".join(diff),
            }
        )

    return {
        "policy_id": ident,
        "from_version": older,
        "to_version": newer,
        "added": added,
        "removed": removed,
        "modified": modified,
        "unchanged_count": unchanged,
        "summary": (
            f"{len(added)} section(s) added, {len(removed)} removed, "
            f"{len(modified)} reworded, {unchanged} unchanged."
        ),
    }


def main() -> None:
    try:
        settings = Settings.from_env()
        if not settings.is_mock:
            # Fail loudly at startup rather than on the first tool call, so the
            # problem shows up in `claude mcp list` instead of mid-conversation.
            raise graph_store_unavailable()
    except ConfigError as exc:
        print(f"sharepoint-policy-mcp: configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    log.info(
        "sharepoint-policy-mcp starting (auth_mode=%s, libraries=%d, groups=%s, redaction=%s)",
        settings.auth_mode,
        len(settings.allowed_libraries),
        ",".join(settings.user_groups),
        settings.redact,
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
