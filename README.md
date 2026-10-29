# Agent Toolforge

Ten production-grade building blocks for AI agents — 5 MCP servers + 5 Claude/Codex skills — each targeting a documented, evidence-backed gap in today's agent tooling (token bloat, cross-session memory, crash recovery, verification, citation integrity, tool-call reliability, cost attribution, scheduling safety, multimodal file reads).

Every product is a self-contained MVP: a stdlib-only pure-Python core with a real `unittest` suite, plus a thin MCP wrapper (for MCP products) or a `SKILL.md` (for skills). No paid keys, minimal dependencies.

## Products

### MCP servers

| Product | Gap it closes | Core |
|---|---|---|
| [`mcp-slim-proxy`](products/mcp-slim-proxy/) | MCP responses blow up the context window (single payload 67k tokens → 25k limit error) | Field-projection / pagination / truncation middleware; reports token reduction % |
| [`agent-memory-core`](products/agent-memory-core/) | Existing memory servers only store/fetch — no fact extraction, entity linking, or recency | SQLite memory: extract facts + entities, relevance+recency ranked recall, entity filter |
| [`toolcall-guard`](products/toolcall-guard/) | Bad tool-call args trigger infinite retry loops | Minimal JSON-Schema validation + typed correction hints + best-effort JSON repair |
| [`token-ledger`](products/token-ledger/) | Bills show totals, not which session/agent burned the tokens | Per-session/model/tag cost attribution + statistical spike detection |
| [`multimodal-fs`](products/multimodal-fs/) | Filesystem MCP `read_file` degrades on images/PDFs (issue #533) | MIME-aware reader: text / image (base64 block) / PDF (graceful pypdf fallback) |

### Skills

| Product | Gap it closes | Core |
|---|---|---|
| [`checkpoint-resume`](products/checkpoint-resume/) | Long batch job crashes at item 201 → restart from zero | Atomic-write checkpoint helper (index + state + done set), exact resume |
| [`verify-done`](products/verify-done/) | Agents claim "done" without running anything | Read-back + restart-aware + smoke-test check runner with honest pass/fail |
| [`fresh-eyes-review`](products/fresh-eyes-review/) | Same-context self-review rubber-stamps its own code | Fresh-context adversarial review prompt builder + diff parser + severity rubric |
| [`citation-verifier`](products/citation-verifier/) | 11–57% of agent report citations are fabricated | URL/`[Source]` extraction + liveness classification + suspicious-placeholder heuristics |
| [`cron-guard`](products/cron-guard/) | Scheduled agents overlap, run away on cost, leave no audit | Atomic lock (no overlap) + budget cap + append-only audit log wrapper |

## Layout

```
products/<slug>/
  *.py / src/        core logic (stdlib only)
  server.py          thin MCP wrapper (MCP products)
  SKILL.md           trigger + protocol (skill products)
  SPEC.md            requirement + interface contract
  README.md          usage + install + test command
  tests/             unittest suite
```

## Run the tests

```bash
cd products/<slug> && python3 -m unittest discover -s tests -p 'test_*.py' -v
```

All ten suites pass on Python 3 (257 tests in total as of 2026-10-29;
256 pass and one optional PDF test skips when `pypdf` is absent). The core
and tests require no install step; optional PDF extraction uses `pypdf`.

## Error contract (fail closed)

Since the batch-11 hardening, malformed input is rejected explicitly instead of
being silently tolerated. Callers that relied on the old lenient behaviour now get
a `ValueError` (or `TypeError`): negative `max_items` / string `fields` / bool
limits in `mcp-slim-proxy`; non-int or negative `expect_exit`, non-string or empty
`expect_substr`, empty `must_contain` in `verify-done`; negative `index` in
`checkpoint-resume`; non-finite `ts` and non-positive or bool `limit` in
`agent-memory-core`; unknown model or bad pricing in `token-ledger`. See each
product's README for its exact contract and its **已知限制** (known limitations)
notes (e.g. `verify-done` `run_checks([])`, `token-ledger` `detect_spikes` on short
series, `cron-guard` PID reuse).

## Status

MVP. Each core is runnable and tested; MCP wrappers import their SDK behind a guard so cores and tests run even without the `mcp` package installed.

## License

MIT
