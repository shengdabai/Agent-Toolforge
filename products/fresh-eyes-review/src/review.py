"""fresh-eyes-review core helper.

Pure standard-library logic for building an adversarial, fresh-context code
review prompt and for parsing unified diffs into a per-file change summary.

No network access, no third-party dependencies. Safe to import anywhere.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

__all__ = [
    "DEFAULT_CHECKLIST",
    "SEVERITY_RUBRIC",
    "ADVERSARIAL_DISAVOWAL",
    "build_review_prompt",
    "parse_diff",
]

# The single most important line: force a fresh, adversarial stance so the
# reviewer never rubber-stamps code it (or its own prior context) produced.
ADVERSARIAL_DISAVOWAL = "You did NOT write this code. Review it adversarially."

# Default review dimensions. Ordered from most to least likely to block a merge.
DEFAULT_CHECKLIST: List[str] = [
    "Correctness: does the logic actually do what it claims? Off-by-one, "
    "inverted conditions, wrong operators, broken control flow.",
    "Security: untrusted input, injection, secrets in code, unsafe "
    "deserialization, missing authz, path traversal.",
    "Edge cases: empty inputs, None/null, zero, negatives, very large values, "
    "unicode, concurrency, boundary conditions.",
    "Error handling: swallowed exceptions, missing try/except, unchecked "
    "return values, silent failures, bad error messages.",
    "Duplication: repeated logic that should be extracted, copy-paste drift, "
    "reinvented stdlib helpers.",
]

# Severity rubric. Each tier names a concrete consequence so the reviewer
# grades impact, not vibes.
SEVERITY_RUBRIC: List[Dict[str, str]] = [
    {
        "level": "critical",
        "definition": (
            "Correctness, security, or data-loss defect. Must block merge. "
            "Do not approve until fixed."
        ),
    },
    {
        "level": "major",
        "definition": (
            "Significant bug, missing edge-case handling, or risky design. "
            "Should block merge unless explicitly justified."
        ),
    },
    {
        "level": "minor",
        "definition": (
            "Style, naming, small duplication, or non-blocking improvement. "
            "Note it, but it does not block merge."
        ),
    },
]


def _render_severity_rubric() -> str:
    lines = ["Severity rubric (rate every finding):"]
    for tier in SEVERITY_RUBRIC:
        lines.append(f"- {tier['level'].upper()}: {tier['definition']}")
    return "\n".join(lines)


def _render_checklist(checklist: Optional[List[str]]) -> str:
    items = checklist if checklist else DEFAULT_CHECKLIST
    lines = ["Review checklist (work through each dimension):"]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item}")
    return "\n".join(lines)


def _render_change_summary(diff: str) -> str:
    entries = parse_diff(diff)
    if not entries:
        return "Changed files: (no recognizable diff headers found)"
    lines = ["Changed files (blast radius):"]
    for e in entries:
        lines.append(
            f"- {e['file']}: +{e['added_lines']} / -{e['removed_lines']}"
        )
    return "\n".join(lines)


def build_review_prompt(
    diff: str,
    context: Optional[str] = None,
    checklist: Optional[List[str]] = None,
) -> str:
    """Build an adversarial fresh-context code-review prompt.

    The returned prompt always contains:
      * the adversarial disavowal line,
      * a critical/major/minor severity rubric with definitions,
      * a review checklist (the default if ``checklist`` is falsy),
      * a parsed summary of changed files,
      * the raw diff itself,
      * optional reviewer context.

    Args:
        diff: A unified diff string under review.
        context: Optional extra context (system, constraints, prior intent).
        checklist: Optional custom checklist. ``None`` or ``[]`` -> default.

    Returns:
        A single prompt string ready to hand to a fresh reviewer agent.
    """
    diff = diff if isinstance(diff, str) else ""

    sections: List[str] = []
    sections.append(ADVERSARIAL_DISAVOWAL)
    sections.append(
        "You are an independent reviewer in a fresh context. You have no "
        "stake in this change and no memory of writing it. Assume it is "
        "wrong until the diff proves otherwise. Be specific: cite file and "
        "the offending line for every finding."
    )

    if context:
        sections.append("Reviewer context:\n" + str(context).strip())

    sections.append(_render_severity_rubric())
    sections.append(_render_checklist(checklist))
    sections.append(_render_change_summary(diff))
    sections.append("Diff under review:\n```diff\n" + diff + "\n```")
    sections.append(
        "Output: a list of findings, each tagged [CRITICAL] / [MAJOR] / "
        "[MINOR] with file:line and a concrete fix. End with a verdict: "
        "APPROVE only if there are zero CRITICAL and zero MAJOR findings; "
        "otherwise REQUEST CHANGES."
    )

    return "\n\n".join(sections)


_PATH_ESCAPES = {
    b"a": b"\a", b"b": b"\b", b"f": b"\f", b"n": b"\n",
    b"r": b"\r", b"t": b"\t", b"v": b"\v", b'"': b'"', b"\\": b"\\",
}


def _decode_path(raw: str) -> str:
    """Decode Git's quoted path format, excluding any tab-separated metadata."""
    # Drop a trailing tab + metadata (e.g. timestamps) if present.
    token = raw.split("\t", 1)[0]
    if token.startswith('"') and token.endswith('"'):
        # Git quotes unusual paths with C escapes. Octal escapes represent
        # UTF-8 bytes, not individual Unicode characters.
        encoded = token[1:-1].encode("utf-8", errors="surrogateescape")
        encoded = re.sub(
            rb'\\([0-3][0-7]{2}|[abfnrtv"\\])',
            lambda m: (bytes([int(m[1], 8)]) if m[1][:1].isdigit()
                       else _PATH_ESCAPES[m[1]]),
            encoded,
        )
        token = encoded.decode("utf-8", errors="surrogateescape")
    return token


def _strip_prefix(raw: str) -> Optional[str]:
    """Decode a diff path, strip a/ or b/, and ignore /dev/null sentinels."""
    token = _decode_path(raw)
    if not token or token == "/dev/null":
        return None
    if token.startswith("a/") or token.startswith("b/"):
        return token[2:]
    return token


# "@@ -old_start[,old_len] +new_start[,new_len] @@" — a missing length means 1.
_HUNK_RE = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
_GIT_HEADER_RE = re.compile(
    r'^diff --git ("(?:\\.|[^"\\])*"|a/.*?) ("(?:\\.|[^"\\])*"|b/.*)$'
)


def parse_diff(diff_text: Optional[str]) -> List[Dict[str, object]]:
    """Parse a unified diff into per-file change counts.

    Args:
        diff_text: Unified diff text (``git diff`` / ``diff -u`` style).
            ``None`` or non-string input yields an empty list.

    Returns:
        A list of dicts, one per file, each shaped::

            {"file": str, "added_lines": int, "removed_lines": int}

        Files appear in first-seen order. Hunk headers (``@@``), file
        headers (``---``/``+++``), and ``diff --git`` lines are never
        counted as added/removed content. Text with no recognizable
        diff headers returns ``[]``.
    """
    if not isinstance(diff_text, str) or not diff_text:
        return []

    order: List[str] = []
    files: Dict[str, Dict[str, object]] = {}
    current: Optional[str] = None
    old_path: Optional[str] = None

    def ensure(name: str) -> Dict[str, object]:
        if name not in files:
            files[name] = {"file": name, "added_lines": 0, "removed_lines": 0}
            order.append(name)
        return files[name]

    # Lines still owed by the current hunk. While a hunk is open every line is
    # content, so a removed "-- sql comment" (rendered "--- sql comment") or an
    # added "++ x" is counted instead of being mistaken for a file header.
    old_left = 0
    new_left = 0

    # A diff record ends at LF. Unicode separators and control characters can
    # occur inside source lines; splitlines() would turn them into headers.
    lines = diff_text.split("\n")
    for line in lines:
        line = line.removesuffix("\r")  # Accept pasted CRLF diffs as well.
        if current is not None and (old_left > 0 or new_left > 0):
            if line.startswith("\\"):
                continue  # "\ No newline at end of file"
            if line.startswith("+"):
                files[current]["added_lines"] = files[current]["added_lines"] + 1  # type: ignore[operator]
                new_left -= 1
                continue
            if line.startswith("-"):
                files[current]["removed_lines"] = files[current]["removed_lines"] + 1  # type: ignore[operator]
                old_left -= 1
                continue
            if line.startswith(" ") or line == "":
                old_left -= 1
                new_left -= 1
                continue
            # Anything else means the hunk was shorter than declared; fall
            # through and treat the line as a header.
            old_left = new_left = 0
        if line.startswith("diff --git "):
            # "diff --git a/x b/x" -> prefer the b/ path (post-image name).
            if current is not None:
                ensure(current)
            current = old_path = None
            # A new file header closes any hunk, including one opened before
            # the first file header (e.g. a pasted diff that starts with "@@").
            old_left = new_left = 0
            match = _GIT_HEADER_RE.match(line)
            # Empty/binary files may have no ---/+++ headers. If both paths
            # are identical, match the whole suffix rather than splitting on
            # a " b/" that belongs to the filename.
            same_path = re.fullmatch(r"diff --git a/(.*) b/\1", line)
            # Preserve support for simple --no-prefix/custom-prefix headers.
            paths = match.groups() if match else line[11:].split(" ", 1)
            if same_path:
                current = same_path[1]
            elif len(paths) == 2:
                name = _strip_prefix(paths[1]) or _strip_prefix(paths[0])
                if name:
                    current = name
                    # The later +++ or rename header is authoritative. Delay
                    # registration so ambiguous paths cannot leave a phantom.
            continue
        if line.startswith("--- "):
            # Wait for +++ before registering a plain unified diff. Its old
            # and new labels can differ; a deletion uses the old label.
            old_path = _strip_prefix(line[4:])
            continue
        if line.startswith("+++ "):
            name = _strip_prefix(line[4:]) or old_path
            if name:
                # The +++ (post-image) path is authoritative for the file name.
                current = name
                ensure(current)
            continue
        if line.startswith(("rename to ", "copy to ")):
            if current is not None:
                current = _decode_path(line.split(" to ", 1)[1])
            continue
        if line.startswith("@@"):
            # Hunk header: never counted.
            if current is not None:
                ensure(current)
            m = _HUNK_RE.match(line)
            if m:
                old_left = int(m.group(1)) if m.group(1) is not None else 1
                new_left = int(m.group(2)) if m.group(2) is not None else 1
            continue
        if current is None:
            # Content before any header => not a real diff line.
            continue
        if line.startswith("+"):
            ensure(current)
            files[current]["added_lines"] = files[current]["added_lines"] + 1  # type: ignore[operator]
        elif line.startswith("-"):
            ensure(current)
            files[current]["removed_lines"] = files[current]["removed_lines"] + 1  # type: ignore[operator]

    if current is not None:
        ensure(current)
    return [files[name] for name in order]
