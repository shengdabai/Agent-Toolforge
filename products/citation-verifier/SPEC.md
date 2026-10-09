# SPEC — citation-verifier

## Problem

Agent- and model-generated reports fabricate or corrupt citations at rates of
11–57%. Fabricated URLs and invented DOIs/arXiv ids pass as evidence. This
product audits citations in text so the failure is caught before delivery.

## Form

**Skill.** A `SKILL.md` with standard frontmatter (`name` + trigger-rich
`description`) plus a pure-Python, stdlib-only helper module and unittests.

## Requirements (filled)

| # | Requirement | Decision |
|---|-------------|----------|
| R1 | Extract citations from text | `extract_citations` returns URLs (regex) and `[Source: ...]` annotations |
| R2 | Determine reachability | `classify` maps each URL to `live` / `dead` / `unreachable` via injected fetcher |
| R3 | Network must be testable offline | fetcher is a `(url) -> status_code \| None` callable injected by caller |
| R4 | Aggregate audit | `audit` returns counts + `suspicious` list |
| R5 | Detect fabrication heuristically | placeholder hosts/paths, malformed arXiv ids, malformed DOIs |
| R6 | Wayback fallback | optional `resilient_fetcher` consults Internet Archive for dead links |
| R7 | No third-party deps | core uses `re` only; fetchers use `urllib` only |

## Interface contract

```python
extract_citations(text: str) -> {"urls": list[str], "sources": list[str]}
    # Order-preserving, de-duplicated. Trailing prose punctuation trimmed
    # from URLs. Empty text / no matches -> empty lists.

classify(urls: list[str], fetcher: Callable[[str], int | None]) -> dict[str, str]
    # status None        -> "unreachable"
    # 200 <= status < 400 -> "live"
    # otherwise (4xx/5xx) -> "dead"
    # fetcher raising     -> "unreachable"

audit(text: str, fetcher) -> {
    "total": int,            # distinct URLs checked
    "live": int,
    "dead": int,
    "unreachable": int,
    "suspicious": list[str], # placeholder URLs + malformed arXiv/DOI ids
}
```

### Suspicion rules

- URL host equals or is a subdomain of a placeholder host (`example.com/.org/.net`, `test.com`) or a
  whole path segment equals a placeholder token (`/xxx`, `/yyy`, `/zzz`, `/foo`, `/bar`,
  `/placeholder`, `/todo`).
- arXiv reference (`arxiv.org/abs|pdf/<id>` or `arxiv:<id>`) whose id does not
  match `^\d{4}\.\d{4,5}(v\d+)?$` or the pre-2007 form `archive[.XX]/NNNNNNN`
  (a trailing `.pdf`, query or fragment is ignored).
- A fetcher result that is not a real `int` status counts as `unreachable`.
- DOI reference (`doi:<id>`) whose id does not match `^10\.\d{4,9}/\S+$`.

## Out of scope

- Judging whether the *content* of a live page supports the claim (semantic
  fact-checking) — this product only verifies that the citation resolves and is
  well-formed.
- Rendering or scraping page bodies.

## Test plan

`python3 -m unittest discover -s tests -p 'test_*.py'` covering: multi-URL +
source extraction, dedupe, punctuation trimming, live/dead/unreachable
classification (incl. 2xx/3xx and fetcher exception), audit counts, all-zero on
empty text, and each suspicion heuristic (placeholder, bad arXiv, bad DOI) plus
negative cases (valid arXiv/Nature URL not flagged).
