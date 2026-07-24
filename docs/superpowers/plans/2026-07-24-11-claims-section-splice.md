# Claims Section Splice Implementation Plan

**Goal:** Close the biggest gap flagged in phase 09's roadmap review — `analyze_pending_documents`
extracts claims via LLM but never writes them back into the document body. This phase splices
the extracted `Claim`s into the "## 핵심 주장" / "## 근거" / "## 반대 근거" / "## 언급 자산"
placeholder sections that every collector's renderer already emits (they were deliberately given
identical header names across all 5 sources for exactly this purpose — see phase 03's plan
self-review note).

**Scope decision (only the 4 claim-derived sections are touched):** "## 원문" and the
limitations section (whose header text varies per source — "13F 해석 시 유의사항" vs "공시
해석 시 유의사항" vs "블로그/텔레그램 수집 시 유의사항") are left completely untouched by
splicing whatever wasn't matched back verbatim. "## 포트폴리오 관련성" and "## 출처" are
likewise untouched — portfolio relevance synthesis is `llm/portfolio_impact.py`'s job (phase 09),
not this one's.

## Task breakdown

### Task 1: `pipeline/claims_splice.py`

**Files:** create `investor_intel/pipeline/claims_splice.py`; test
`tests/test_claims_splice.py`.

**Interfaces:** `splice_claims_into_body(body: str, extraction: ExtractionResult) -> str` —
splits `body` on `^## (.+)$` headers (a section is everything between one header and the next,
preamble before the first header preserved as-is), rewrites exactly the 4 claim-derived sections'
content from `extraction.claims` (bulleted claim list with direction/confidence; flattened
evidence; flattened counter_evidence; deduplicated asset list — each with a `(없음)` placeholder
when empty), and reassembles the untouched sections byte-for-byte around them.

- [x] Write failing tests (round-trips a real renderer's output — e.g.
      `render_thirteenf_body`'s output — replacing only the 4 sections; empty-claims list
      produces a "없음" placeholder, not a KeyError; untouched sections' exact whitespace is
      preserved), implement, verify pass
- [x] Commit: `feat: add claims-to-markdown-section splice utility`

### Task 2: Wire into `analyze_pending_documents`

**Files:** modify `investor_intel/pipeline/analyze.py`; extend
`tests/test_pipeline_analyze.py`.

After a successful `extract_claims` call, splice the result into `body` before writing, and
recompute `content_hash` from the **spliced** body (not the original) — the stored hash must
always reflect what's actually on disk, or future dedup/idempotency checks silently drift.

- [ ] Write a failing test (after `analyze_pending_documents` runs, the rewritten file's "## 핵심
      주장" section contains the fake client's claim text, and `content_hash` in the frontmatter
      matches the spliced body's actual hash), implement, verify pass
- [ ] Commit: `feat: splice extracted claims into document sections during analyze`

## Self-review notes

- **Reuse over reimplementation:** relies on the section-header convention already established
  by every renderer since phase 02 — no changes needed to any of the 5 collectors' renderers.
- **Hash consistency is load-bearing:** recomputing `content_hash` after splicing is what keeps
  `write_document`'s idempotency check and `find_duplicate`'s content-hash dedup path honest.
