# citation-verifier

Audit the citations inside agent- or model-generated text and flag fabricated,
dead, or malformed references — before the text ships.

Model-generated references require verification. This tool provides a checklist: extract every citation,
test whether it resolves, and flag placeholders / malformed arXiv ids / bad
DOIs.

## What it does

- **Extract** URLs and `[Source: ...]` annotations from text.
- **Classify** each URL as `live` / `dead` / `unreachable`.
- **Audit** the whole text into counts plus a `suspicious` list.
- **Wayback fallback** (optional) so an archived-but-rotted link is not
  mislabeled as fabricated.

It is packaged as an agent **skill** (`SKILL.md`) but the logic is a plain
Python module you can import anywhere.

## Install

No installation and no third-party packages. The core (`src/citations.py`) uses
only `re`; the optional network layer (`src/fetchers.py`) uses only standard-library HTTP/TLS/socket modules.
Python 3.8+.

```bash
git clone <repo> && cd citation-verifier
```

To use it as a Claude/agent skill, place this directory where your agent
discovers skills (it reads `SKILL.md`).

## Usage

### Offline / testable core

```python
import sys; sys.path.insert(0, "src")
from citations import extract_citations, classify, audit

text = "Per https://arxiv.org/abs/2103.00020 [Source: CLIP 2021] it holds."

extract_citations(text)
# {"urls": ["https://arxiv.org/abs/2103.00020"], "sources": ["CLIP 2021"]}

# Inject any (url)->status_code|None fetcher (great for tests):
fake = {"https://arxiv.org/abs/2103.00020": 200}.get
audit(text, fake)
# {"total": 1, "live": 1, "dead": 0, "unreachable": 0, "suspicious": []}
```

### Real network run

```python
import sys; sys.path.insert(0, "src")
from citations import audit
from fetchers import resilient_fetcher   # HTTP + Wayback fallback

report = audit(open("report.md").read(), resilient_fetcher)
print(report)
```

### Output shape

```json
{
  "total": 3,
  "live": 1,
  "dead": 1,
  "unreachable": 1,
  "suspicious": ["https://example.com/xxx", "arxiv:9999.ABCDE"]
}
```

## Suspicion heuristics

A citation is flagged `suspicious` (even if it resolves) when it uses a
placeholder host/path, a malformed arXiv id, or a malformed DOI (valid form
`10.1038/s41586-...`).

- **Placeholder host**: `example.com` / `example.org` / `example.net` /
  `test.com`, matched exactly or as a parent domain (`www.example.com` is
  flagged, `latest.com` is not).
- **Placeholder path**: `xxx`, `yyy`, `zzz`, `foo`, `bar`, `placeholder`, `todo`,
  matched as a whole path segment (`/foo/page` is flagged, `/food-security` and
  `/barcelona` are not).
- **arXiv id**: valid forms are `2103.00020` (optionally `v2`) and pre-2007
  `hep-th/9901001` / `math.GT/0309136`. A trailing `.pdf`, query string or
  fragment is ignored (`arxiv.org/pdf/2301.12345.pdf` is fine).

## Status classification

`classify` / `audit` map a fetcher result to a label: `200`-`399` -> `live`,
any other integer status (4xx/5xx, ...) -> `dead`. A fetcher that raises, returns
`None`, or returns anything that is not a real `int` (e.g. `"200"` or `True`) is
labelled `unreachable` (fail closed — it is never counted as `live`, and it does
not crash the audit).

## Test

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
# or simply:
python3 -m unittest
```

All tests are stdlib `unittest` and run offline — no network, no `pip install`.

## Layout

```
citation-verifier/
├── SKILL.md            # agent skill: triggers + verification protocol
├── SPEC.md             # requirements + interface contract
├── README.md
├── src/
│   ├── citations.py    # pure stdlib core (extract / classify / audit)
│   └── fetchers.py     # optional public-web HTTP + Wayback fetchers
└── tests/
    └── test_citations.py
```

## Network boundary

Only public HTTP(S) destinations without URL credentials are permitted. Every DNS answer and redirect is checked; the socket connects to the checked numeric address, while HTTPS retains hostname/certificate verification. Private, local, reserved, multicast and address-translation destinations return `unreachable`. Environment proxy settings are intentionally not used. HEAD 405/501 retries GET; the archive JSON body is limited to 1 MiB. Tests use synthetic sockets, not real network services. This does not validate whether the cited content supports a claim.

Archive fallback skips URLs with query strings and strips fragments. Avoid providing private URLs whose secrets appear in path segments. Redirects and fallback share a monotonic budget, but OS DNS resolution and blocking HTTP parsing are not a strict wall-clock sandbox. Run behind a controlled egress boundary when handling hostile input.
