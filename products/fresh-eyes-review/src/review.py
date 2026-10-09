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


def _strip_prefix(raw: str) -> Optional[str]:
    """Strip a unified-diff path token down to a clean repo-relative path.

    Handles ``a/`` and ``b/`` prefixes and ignores ``/dev/null`` sentinels.
    Returns None for /dev/null or empty tokens.
    """
    token = raw.strip()
    # Drop a trailing tab + metadata (e.g. timestamps) if present.
    token = token.split("\t", 1)[0].strip()
    if not token or token == "/dev/null":
        return None
    if token.startswith("a/") or token.startswith("b/"):
        return token[2:]
    return token


# "@@ -old_start[,old_len] +new_start[,new_len] @@" — a missing length means 1.
_HUNK_RE = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


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

    lines = diff_text.splitlines()
    for line in lines:
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
            parts = line.split()
            if len(parts) >= 4:
                name = _strip_prefix(parts[3]) or _strip_prefix(parts[2])
                if name:
                    current = name
                    ensure(current)
            continue
        if line.startswith("--- "):
            # Only adopt this as the file name if we don't already have a
            # better one from a preceding "diff --git" line.
            name = _strip_prefix(line[4:])
            if name and current is None:
                current = name
                ensure(current)
            continue
        if line.startswith("+++ "):
            name = _strip_prefix(line[4:])
            if name:
                # The +++ (post-image) path is authoritative for the file name.
                current = name
                ensure(current)
            continue
        if line.startswith("@@"):
            # Hunk header: never counted.
            m = _HUNK_RE.match(line)
            if m:
                old_left = int(m.group(1)) if m.group(1) is not None else 1
                new_left = int(m.group(2)) if m.group(2) is not None else 1
            continue
        if current is None:
            # Content before any header => not a real diff line.
            continue
        if line.startswith("+"):
            files[current]["added_lines"] = files[current]["added_lines"] + 1  # type: ignore[operator]
        elif line.startswith("-"):
            files[current]["removed_lines"] = files[current]["removed_lines"] + 1  # type: ignore[operator]

    return [files[name] for name in order]
