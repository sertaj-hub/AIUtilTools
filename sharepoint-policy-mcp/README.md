# sharepoint-policy-mcp

A **read-only** [Model Context Protocol](https://modelcontextprotocol.io) server over AML
policy documents — BSA program policy, QA and QC procedures — held in SharePoint. It lets
an MCP client (Claude Code, Claude Desktop, or anything else that speaks the protocol)
retrieve the policy passage that answers a question, **with a citation**, instead of
answering from the model's general knowledge of BSA requirements.

Steps 1 and 2 of the AML case-management assistant: the retrieval layer with its
guardrails, and the ingestion pipeline that turns `.docx` policy into an index. The
Graph-backed store that reaches a real SharePoint site is step 3 — see
[Roadmap](#roadmap).

Built against the Python SDK **`mcp` 2.x**, where the server class is `MCPServer`.
Most tutorials online still show `FastMCP` from `mcp` 1.x — that import does not exist here.

## What it does

| Tool | Purpose |
|---|---|
| `sp_ping` | Connectivity, configuration, and which retrieval method is live. Start here. |
| `sp_list_sources` | Which policies are readable, at which version, owned by whom. |
| `sp_search_policy` | Find passages answering a question. Returns text **plus citation**. |
| `sp_get_section` | One section in full, by `section_id`, when a passage was clipped. |
| `sp_policy_diff` | What changed between two versions of a policy. |

All five are annotated `read_only_hint=True`. There are no write tools, and there will not
be: a policy assistant that can edit policy is a different risk class entirely.

## Quick start (no tenant access needed)

The server ships with a synthetic policy corpus, so you can run every tool before anyone
issues you an app registration.

```bash
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python \
  "mcp>=2,<3" httpx numpy python-docx pytest pytest-asyncio

SP_AUTH_MODE=mock .venv/bin/python -m sharepoint_policy_mcp.server
```

### Register it with Claude Code

A `.mcp.json` is already here, so from this directory:

```bash
claude mcp list          # sharepoint-policy should appear
```

To register it explicitly, or from elsewhere, use absolute paths:

```bash
claude mcp add sharepoint-policy -e SP_AUTH_MODE=mock \
  -- /absolute/path/to/sharepoint-policy-mcp/.venv/bin/python -m sharepoint_policy_mcp.server
```

Then ask your client something like *"how long do I have to file a continuing activity
SAR?"* and it will call `sp_search_policy` and quote BSA-001 §5.1 back at you with the
version and the document URL.

## The synthetic corpus

`corpus.py` holds five documents and 37 sections: a BSA/AML program policy at two versions
(so version comparison has two sides), a QA policy, a QC policy, and one restricted QC
document that exists so entitlement trimming has something to trim.

**The content is synthetic.** It reads like a BSA/AML program policy and the statutory
deadlines in it are the real ones — 30 and 60 days for a SAR, 120 for continuing activity,
15 for a CTR, 14 for a 314(a) response, five years of retention — but it is illustrative
scaffolding for testing retrieval. It is not your institution's policy and it is not legal
advice. `sp_ping` says so in its response, on purpose, so a model reading it knows too.

## Ingestion

Point the pipeline at a folder of `.docx` policies and it writes an index:

```bash
# Generate sample documents from the synthetic corpus, if you have no real ones
.venv/bin/python tools/make_sample_docs.py sample-policies

.venv/bin/python -m sharepoint_policy_mcp.ingest sample-policies -o index
```

Four stages — extract, chunk, embed, persist — and a manifest of content hashes, so a
second run re-embeds only what changed.

**Chunking is section-aware.** Word heading styles are the hierarchy, and in a policy
document they are reliable in a way nothing else about the file is: the numbering scheme
varies, the fonts vary, but somebody applied Heading 1 and Heading 2 because that is how
the table of contents gets built. A section is kept whole when it fits and split on
paragraph then sentence boundaries when it does not. Fixed-width windows cut straight
through that, and the halves are worse than either the whole or a clean split — a window
that ends mid-sentence retrieves on half a clause and cites a rule it does not contain.
Every chunk carries its ancestry, so a clause split off the bottom of 5.1 still cites
*5.1 SAR Filing Deadlines*.

**Provenance is reported, never assumed.** A `.docx` cannot tell you which policy id it
is, which version, who owns it, or who may read it. In production that comes from the
SharePoint columns beside the file; here it comes from a `policies.json` sidecar, falling
back to the filename, and every field that had to be guessed is listed in the run output:

```
+ BSA-001 Program Policy v4.2.docx -> BSA-001 v4.2, 12 sections, 12 chunks
    [inferred: library, effective_date, owner, url]
```

A citation whose version was inferred from a filename is a citation that can be wrong in
the one field an examiner will check.

PDF is deliberately not handled. Policy in a SharePoint library is nearly always the Word
original and the PDF is a rendering of it, and PDF extraction has a much worse failure
mode — silently reordered columns rather than a clean error.

## Retrieval

Two retrievers, fused by rank.

**Lexical: BM25 over heading-boosted sections.** Not an arbitrary default. BSA language is
formulaic and analysts quote it close to verbatim — *"continuing activity"*, *"within 30
calendar days"* — which is the case BM25 handles well and dense retrieval blurs. Three
details carry most of the weight:

- **Heading boost.** Heading tokens are indexed three times. *"SAR Filing Deadlines"*
  beats a body paragraph that mentions deadlines in passing.
- **Query-side acronym expansion.** The corpus writes *"customer due diligence"*; the
  analyst types *"CDD"*. Expansion happens on the query only, so document statistics stay
  untouched. Without it the acronym query returns nothing — and in a compliance tool a
  miss does not read as a miss, it reads as *"the policy is silent"*.
- **`314(a)` survives tokenisation** as `314a`. The difference between 314(a) and 314(b)
  is the difference between answering a law-enforcement request and sharing information
  with another bank.

**Dense: cosine over an embedding index**, persisted as a `.npz` and loaded with the
embedder name it was built with. Vectors from two different models share a space only by
coincidence; comparing them returns confident nonsense, which is the worst failure mode
available to a retrieval system. A mismatch is refused rather than served.

**Fusion: Reciprocal Rank Fusion, not score normalisation.** BM25 scores are unbounded and
corpus-dependent; cosine sits in [-1, 1]. Any scheme that adds them has to invent a scale
factor, and that factor silently becomes the most important tuning parameter in the
system — one nobody set deliberately and nobody can explain to a reviewer. RRF uses only
the ordering each retriever produced, which is the part each is actually good at.

### `SP_RETRIEVAL` defaults to `lexical`, on purpose

The only embedder in the tree is `HashingEmbedder`: a hashing vectoriser that buckets
token hashes and normalises. It is deterministic, offline, and gives real
lexical-overlap similarity — which is exactly why it must not be left on in hybrid mode
and called retrieval. Fusing it with BM25 is a second opinion drawn from the same
evidence. Paraphrase that shares no words with the policy scores **zero**, which is
precisely the gap a real embedder exists to close.

So it is a test rig: it exists so the chunking, indexing and fusion code has something
deterministic to run against with no vendor, no key and no network. `sp_ping` reports
`embedder_is_semantic: false` and the ingestion CLI prints a warning, so nobody mistakes
the rig for retrieval quality. Set `SP_RETRIEVAL=hybrid` once a real embedder is wired in.

Adding one is a single file implementing the three-member `Embedder` protocol
(`name`, `dimensions`, `embed_documents` / `embed_query`). No provider is chosen yet —
the live candidates are Azure OpenAI in your own tenant, a local open-weights model, and
Voyage AI.

### What is still missing

A **reranker** — a cross-encoder over the fused top-N. It is the single biggest quality
lever left, and it is deliberately not built: it needs the step-4 evaluation set to show
it is earning its latency. Tuning it now would mean tuning against vibes.

## Guardrails, and why they are there

Five controls, all on by default.

1. **Mandatory citations.** Every passage carries `policy_id`, `version`, section number,
   effective date, owner and URL. This is the whole point of the server. An analyst who
   asks *"how long do I have to file?"* and gets a confident paragraph with no source has
   been handed something worse than nothing: an answer that reads as authoritative, cannot
   be checked, and will not survive an examiner asking where it came from.
2. **Entitlement trimming, declared rather than silent.** Sections the caller's groups may
   not read are removed — and *counted*. The response says `withheld_by_entitlement: 1`
   and names who to ask. "No policy covers this" and "a policy covers this and you may not
   read it" are different answers, and conflating them misleads the analyst into
   concluding the policy is silent. The count is scoped to results that would have
   appeared on the page, because a warning that fires on every search is one nobody reads.
   Readable results below the cut are promoted to backfill, so a withheld section costs
   the analyst that result, not the slot.
3. **Library allowlist.** The server reaches the policy libraries and nothing else on the
   site, however a question is phrased.
4. **Result and passage caps.** `limit` is clamped to `SP_MAX_LIMIT`; passages are clipped
   to `SP_MAX_PASSAGE_CHARS` on a word boundary, flagged `text_truncated`, and the caller
   gets the `section_id` to fetch the rest.
5. **Value redaction.** QA and QC procedures are full of worked examples, and a worked
   example written in a hurry is where a real account number ends up. Email, SSN and
   card-shaped values are masked on the way out. Section numbers, `314(a)` and dollar
   thresholds are deliberately left alone — a pattern that eats citations makes them
   useless.

None of this substitutes for scoping the app registration to the policy site in Entra ID.
That remains the real control; this is defence in depth.

### The entitlement stopgap you must not ship

`SP_USER_GROUPS` sets the caller's groups **from the environment**, because a stdio MCP
server has no user identity to work from. That is fine for a local prototype and wrong for
production: every analyst running the same config gets the same view, and the
"entitlement" is a value anyone who can edit `.env` can change.

Before this reaches real policy the groups must come from the signed-in user's token, and
the trimming must be checked against SharePoint's own ACLs rather than an `audience` field
we maintain ourselves. Until that is done the server is honest about it: `sp_list_sources`
returns `caller_groups` in every response, so what it is assuming is visible rather than
implied.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SP_AUTH_MODE` | `mock` | `mock` or `graph`. `graph` refuses to start — see Roadmap. |
| `SP_SITE_URL` | — | Bare name, host, or full https URL. Required unless mock. |
| `SP_TENANT_ID` / `SP_CLIENT_ID` / `SP_CLIENT_SECRET` | — | Required for `graph` |
| `SP_ALLOWED_LIBRARIES` | 3 policy libraries | Comma-separated allowlist |
| `SP_USER_GROUPS` | `aml-analyst` | Caller's entitlement groups. A stopgap; see above. |
| `SP_RETRIEVAL` | `lexical` | `lexical` or `hybrid`. See above for why it defaults low. |
| `SP_EMBEDDING_DIMENSIONS` | `512` | Width of the offline test-rig embedder |
| `SP_MAX_LIMIT` | `10` | Hard ceiling on passages per call |
| `SP_DEFAULT_LIMIT` | `5` | Used when the caller omits `limit` |
| `SP_MAX_PASSAGE_CHARS` | `1200` | Passage budget before clipping. Floor of 200. |
| `SP_REDACT` | `true` | Mask email / SSN / card-shaped values in passages |
| `SP_TIMEOUT` | `20` | Per-request timeout, seconds (Graph backend) |
| `SP_MAX_RETRIES` | `3` | Attempts on 429 / 5xx / network error (Graph backend) |
| `SP_LOG_LEVEL` | `INFO` | Logs go to **stderr** only |

Configuration is environment-only and validated at startup, so a bad setup fails in
`claude mcp list` rather than halfway through a conversation. The default group is the
least privileged one on purpose: a misconfiguration should withhold a document, not
disclose one.

`SP_SITE_URL` values beginning `http://` are refused outright — credentials do not go over
an unencrypted channel.

## Tests

```bash
.venv/bin/python -m pytest -q
```

187 tests, no network and no credentials. They cover tokenisation and ranking, chunk
boundaries and budgets, extraction from real `.docx` files written by the tests
themselves, provenance inference, delta sync, vector persistence, rank fusion, the
entitlement and allowlist checks, passage clipping, redaction, and every tool end to end
through the MCP dispatcher the way a client calls it.

The guardrail tests matter more than the count. The entitlement checks are not mock
behaviour standing in for the real thing — they are the real checks, running over mock
data. A control that only exists in the production path is a control nobody has ever seen
fail.

## Layout

```
sharepoint_policy_mcp/
  config.py      Settings from env, site normalisation, allowlist, entitlement predicates
  models.py      Document, Section, Chunk, Hit -- citations live on the model itself
  corpus.py      The synthetic policy corpus
  extract.py     .docx -> a hierarchy of sections, via Word heading styles
  chunking.py    Section-aware splitting with ancestry and overlap
  embedder.py    Embedder protocol + HashingEmbedder (offline test rig)
  vectors.py     On-disk cosine index, refuses a mismatched embedder
  hybrid.py      Reciprocal rank fusion
  ingest.py      The pipeline and its CLI, with content-hash delta sync
  search.py      BM25 with heading boost, policy-aware tokenisation, query expansion
  store.py       PolicyStore protocol, MockPolicyStore, entitlement trimming
  redaction.py   Value-pattern masking for passages
  server.py      MCPServer instance and the five tools
tools/           make_sample_docs.py -- writes the corpus out as .docx
tests/           187 tests across the modules above
```

## Roadmap

Where this sits in the larger build:

1. **This server, mock-backed.** Done.
2. **Ingestion pipeline.** Done, for documents on disk: extract → section-aware chunking →
   embed → persist, with delta sync on content hash. Still to come: a real embedder, and
   fetching the documents from Graph rather than a folder.
3. **Graph-backed store.** Entra ID app registration with `Sites.Selected`, scoped to the
   policy site. Per-user entitlement trimming against real ACLs, replacing
   `SP_USER_GROUPS`. `SP_AUTH_MODE=graph` exits with a clear message until this lands,
   rather than half-working against a real tenant.
4. **Evaluation harness.** ~50 analyst questions with known-correct citations, measuring
   retrieval recall and citation accuracy. Nothing is tuned before there is a set to tune
   against — the BM25 parameters here are the textbook defaults for exactly that reason.
5. **Agent layer.** Then, optionally, joining to `servicenow_mcp` for case-aware answers.

### Scope boundary

This is **advisory, citing policy**. It does not decide SAR/no-SAR, close alerts, or draft
narratives that go to FinCEN unreviewed. That line is where model risk management (SR
11-7) and your validation group will focus, and it is worth holding deliberately rather
than drifting across it one feature at a time.

## Gotchas worth knowing

- **Never print to stdout.** Stdout *is* the MCP transport. A stray `print()` corrupts the
  protocol stream and the client drops the server. All logging here goes to stderr.
- **Raise `ToolError`, not `ValueError`.** In `mcp` 2.x an anticipated failure raised as
  `ToolError` returns its message to the model. Any other exception becomes
  `UnexpectedToolError` and the model sees only *"Error executing tool X"* — the useful
  detail is withheld.
- **`ToolAnnotations` uses snake_case** (`read_only_hint`), and `Tool.input_schema` is
  snake_case too. The wire protocol is camelCase; the Python objects are not.
- **Entitlement filtering runs after scoring, not before.** Filtering inside the ranker's
  predicate and then capping would drop results the caller was entitled to see, and would
  count every unreadable section in the corpus as "withheld". Both are easy to write and
  wrong in ways that only show up in front of an analyst.
