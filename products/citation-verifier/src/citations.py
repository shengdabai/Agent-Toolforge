"""citation-verifier core helper.

Pure-Python, standard-library-only logic for auditing the citations inside a
block of agent- or model-generated text. Designed so the heuristics are fully
testable without any network access: the network is injected via a ``fetcher``
callable ``(url) -> status_code | None``.

Public API
----------
extract_citations(text)        -> {"urls": [...], "sources": [...]}
classify(urls, fetcher)        -> {url: "live" | "dead" | "unreachable"}
audit(text, fetcher)           -> {"total", "live", "dead", "unreachable", "suspicious"}
"""
from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional
from urllib.parse import urlsplit

# A fetcher maps a URL to an HTTP status code, or None when the host could not
# be reached at all (DNS failure, connection refused, timeout, ...).
Fetcher = Callable[[str], Optional[int]]

# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #

# Match http(s) URLs. We grab a generous run of URL-ish characters and then trim
# trailing punctuation that almost always belongs to the surrounding prose.
_URL_RE = re.compile(r"https?://[^\s<>\"'\]\}]+", re.IGNORECASE)

# Match [Source: ...] annotations (case-insensitive label, lazy body).
_SOURCE_RE = re.compile(r"\[\s*source\s*:\s*(.*?)\s*\]", re.IGNORECASE | re.DOTALL)

# Punctuation that should be stripped from the tail of a captured URL.
_TRAILING_PUNCT = ".,;:!?)]}\"'>"


def _trim_url(url: str) -> str:
    """Strip trailing prose punctuation while keeping balanced parens."""
    while url and url[-1] in _TRAILING_PUNCT:
        # Keep a closing paren only if the URL itself opened one.
        if url[-1] == ")" and url.count("(") > url.count(")"):
            break
        url = url[:-1]
    return url


def _dedupe(items: List[str]) -> List[str]:
    """Order-preserving de-duplication."""
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def extract_citations(text: str) -> Dict[str, List[str]]:
    """Pull URLs and ``[Source: ...]`` annotations out of *text*.

    Returns a dict with two order-preserving, de-duplicated lists::

        {"urls": [...], "sources": [...]}
    """
    if not text:
        return {"urls": [], "sources": []}

    urls = [_trim_url(m.group(0)) for m in _URL_RE.finditer(text)]
    urls = [u for u in urls if u]

    sources = [m.group(1).strip() for m in _SOURCE_RE.finditer(text)]
    sources = [s for s in sources if s]

    return {"urls": _dedupe(urls), "sources": _dedupe(sources)}


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def _status_to_label(status: Optional[int]) -> str:
    # A fetcher returning anything but a real int status (None, "200", True)
    # proved nothing; never let it crash the audit or count as live.
    if not isinstance(status, int) or isinstance(status, bool):
        return "unreachable"
    if 200 <= status < 400:
        return "live"
    return "dead"  # 4xx / 5xx (and any other non-success code)


def classify(urls: List[str], fetcher: Fetcher) -> Dict[str, str]:
    """Classify each URL as ``live`` / ``dead`` / ``unreachable``.

    ``fetcher`` is injected so tests can run offline. A fetcher that raises is
    treated the same as one returning ``None`` (the host is unreachable).
    """
    result: Dict[str, str] = {}
    for url in urls:
        try:
            status = fetcher(url)
        except Exception:
            status = None
        result[url] = _status_to_label(status)
    return result


# --------------------------------------------------------------------------- #
# Suspicion heuristics
# --------------------------------------------------------------------------- #

# Obvious placeholder / example hosts and path tokens that real citations
# almost never use.
_PLACEHOLDER_HOSTS = ("example.com", "example.org", "example.net", "test.com")
_PLACEHOLDER_TOKENS = ("/xxx", "/yyy", "/zzz", "/foo", "/bar", "/placeholder", "/todo")

# Valid arXiv ids: YYMM.NNNNN (4-digit prefix, 4-5 digit suffix), optional v#.
_ARXIV_REF_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([^\s)\]\"']+)", re.IGNORECASE)
_ARXIV_BARE_RE = re.compile(r"\barxiv\s*:\s*([^\s)\]\"']+)", re.IGNORECASE)
_ARXIV_VALID_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
# Pre-2007 identifiers: archive[.SUBJ]/YYMMNNN, e.g. hep-th/9901001, math.GT/0309136.
_ARXIV_OLD_RE = re.compile(r"^[a-z][a-z-]*(\.[A-Za-z]{2})?/\d{7}(v\d+)?$", re.IGNORECASE)

# DOI references. A valid DOI is 10.<registrant>/<suffix>.
_DOI_REF_RE = re.compile(r"\bdoi\s*:\s*([^\s)\]\"']+)", re.IGNORECASE)
_DOI_VALID_RE = re.compile(r"^10\.\d{4,9}/\S+$")


def _is_placeholder_url(url: str) -> bool:
    """Match placeholder hosts exactly (or as a parent domain) and placeholder
    tokens as whole path segments, so ``latest.com`` or ``/food-security`` are
    not mistaken for ``test.com`` / ``/foo``."""
    try:
        parts = urlsplit(url.lower())
        host = parts.hostname or ""
    except ValueError:
        return True  # unparseable URL is not a credible citation
    if any(host == h or host.endswith("." + h) for h in _PLACEHOLDER_HOSTS):
        return True
    segments = set(seg for seg in parts.path.split("/") if seg)
    return any(tok.lstrip("/") in segments for tok in _PLACEHOLDER_TOKENS)


def _suspicious_arxiv(text: str) -> List[str]:
    flagged = []
    for m in list(_ARXIV_REF_RE.finditer(text)) + list(_ARXIV_BARE_RE.finditer(text)):
        ident = m.group(1).strip().rstrip(".,;:)]}")
        # "arxiv.org/pdf/2301.12345.pdf" is the normal PDF link form; drop any
        # URL query/fragment too before judging the identifier itself.
        ident = re.split(r"[?#]", ident, maxsplit=1)[0]
        if ident.lower().endswith(".pdf"):
            ident = ident[:-4]
        if not (_ARXIV_VALID_RE.match(ident) or _ARXIV_OLD_RE.match(ident)):
            flagged.append("arxiv:" + ident)
    return flagged


def _suspicious_doi(text: str) -> List[str]:
    flagged = []
    for m in _DOI_REF_RE.finditer(text):
        ident = m.group(1).strip().rstrip(".,;:)]}")
        if not _DOI_VALID_RE.match(ident):
            flagged.append("doi:" + ident)
    return flagged


def find_suspicious(text: str, urls: List[str]) -> List[str]:
    """Return citations that look fabricated or are obvious placeholders."""
    suspicious: List[str] = []
    for url in urls:
        if _is_placeholder_url(url):
            suspicious.append(url)
    suspicious.extend(_suspicious_arxiv(text))
    suspicious.extend(_suspicious_doi(text))
    return _dedupe(suspicious)


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #


def audit(text: str, fetcher: Fetcher) -> Dict[str, object]:
    """Audit every citation in *text*.

    Returns::

        {
          "total": int,            # number of distinct URLs checked
          "live": int,
          "dead": int,
          "unreachable": int,
          "suspicious": [str, ...] # placeholder / malformed identifiers
        }
    """
    extracted = extract_citations(text)
    urls = extracted["urls"]

    classified = classify(urls, fetcher)
    counts = {"live": 0, "dead": 0, "unreachable": 0}
    for label in classified.values():
        counts[label] += 1

    return {
        "total": len(urls),
        "live": counts["live"],
        "dead": counts["dead"],
        "unreachable": counts["unreachable"],
        "suspicious": find_suspicious(text, urls),
    }
