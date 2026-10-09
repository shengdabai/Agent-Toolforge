---
name: citation-verifier
description: Verify and audit the citations in agent- or model-generated text before it ships. Use when the user mentions citation check, citation verification, fact-check the citations / references, verify sources, check whether URLs or references are real, detect fabricated citations or hallucinated links, or asks to audit a report's bibliography. Triggers include "引用核验", "引证", "查证", "参考文献核对", "fact-check 引用", "citation", "verify sources", "are these links real".
---

# Citation Verifier

Reports from LLM agents fabricate or mangle citations at high rates — published
audits put the share of wrong or invented references anywhere from **11% to 57%**
depending on the model and task. A confident answer with a dead or made-up link
is worse than no link: it launders a guess as evidence. This skill catches that
before the text reaches a human.

## When to use

- A draft, report, or answer contains URLs or `[Source: ...]` markers.
- You are about to ship text that cites studies, articles, DOIs, or arXiv papers.
- The user asks to "verify the citations", "check if these links are real",
  "fact-check the references", or any of the trigger phrases above.

## The core helper

`src/citations.py` is pure standard-library Python. The network is injected, so
the logic is deterministic and testable:

```python
import sys; sys.path.insert(0, "src")
from citations import extract_citations, classify, audit

# 1. Pull URLs and [Source: ...] annotations out of the text.
cites = extract_citations(text)          # {"urls": [...], "sources": [...]}

# 2. Classify reachability. Inject any (url)->status_code|None fetcher.
labels = classify(cites["urls"], fetcher)  # {url: "live"|"dead"|"unreachable"}

# 3. Full audit in one call.
report = audit(text, fetcher)
# -> {"total", "live", "dead", "unreachable", "suspicious": [...]}
```

For a real run, use the optional `src/fetchers.py` (stdlib `urllib` only):

```python
from fetchers import resilient_fetcher   # HTTP check + Wayback fallback
report = audit(text, resilient_fetcher)
```

`resilient_fetcher` first does a live HTTP check, then falls back to the
**Internet Archive Wayback Machine** so a link that has rotted but was archived
is restored to `live` instead of being condemned as fabricated.

## Suspicion heuristics (no network needed)

`audit` flags entries as `suspicious` when:

- the URL uses an obvious placeholder host or path
  (`example.com`, `example.org`, `/xxx`, `/foo`, `/placeholder`, ...). Hosts match
  exactly or as a parent domain; path tokens match whole segments only, so
  `latest.com` and `/food-security` are not flagged;
- an **arXiv** reference has a malformed id (valid forms: `YYMM.NNNNN`, e.g.
  `2103.00020`, optional `v2`, and pre-2007 `hep-th/9901001`; a trailing `.pdf`
  or query/fragment is ignored);
- a **DOI** does not match `10.<registrant>/<suffix>`.

Suspicious entries deserve manual eyes even if the fetcher reports `live`,
because a placeholder host can still 200.

## Verification protocol — ground every claim in a real source

Run this loop on any draft before delivery:

1. **Extract.** `extract_citations(text)` — list every URL and `[Source: ...]`.
2. **Map claims to sources.** For each factual claim in the text, confirm it
   points at a specific source. A claim with no citation is itself suspicious —
   either cite it or soften it to an explicit assumption.
3. **Audit reachability.** `audit(text, resilient_fetcher)`.
4. **Triage the report:**
   - `live` → status 200-399. A fetcher result that is not a real integer (`None`,
     `"200"`, `True`) or a fetcher that raises is reported as `unreachable`, never `live`.
   - `dead` → the URL returned 4xx/5xx and has no Wayback snapshot. Replace the
     link, find the canonical URL, or remove the claim.
   - `unreachable` → host did not answer. Retry once; if still down, treat as
     unverified and label it as such, do not silently keep it.
   - `suspicious` → inspect by hand; verify the arXiv/DOI id resolves to the
     paper actually being cited, not just *a* paper.
5. **Wayback fallback.** For any salvageable dead link, cite the archived
   snapshot URL (`https://web.archive.org/web/<timestamp>/<url>`) so the
   evidence stays reachable.
6. **Report honestly.** Surface the counts (`live/dead/unreachable/suspicious`).
   Never round an unverified citation up to "verified".

## Anti-patterns

- Do **not** declare citations "checked" without actually running the audit.
- Do **not** treat `suspicious` as harmless just because the fetcher said `live`.
- Do **not** invent a replacement URL for a dead link — find the real one or
  drop the claim.

## Tests

```
python3 -m unittest discover -s tests -p 'test_*.py' -v
```
