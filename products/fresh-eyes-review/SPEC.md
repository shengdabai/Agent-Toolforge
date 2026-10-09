# SPEC — fresh-eyes-review

## Problem

An AI coding agent that reviews its own diff inside the same context
overwhelmingly approves it. Shared context = shared blind spots = a review
that is really just a signature. We need a way to force an **independent,
adversarial** review pass that does not reuse the authoring context.

## Form

Skill. Ships a `SKILL.md` (trigger-rich frontmatter + reviewer protocol) plus
a pure-stdlib Python helper (`src/review.py`) with `unittest` coverage.

## Requirements (fill-in contract)

| ID | Requirement | Status |
|----|-------------|--------|
| R1 | `build_review_prompt` output contains the literal adversarial disavowal line. | done |
| R2 | Output contains a severity rubric naming critical / major / minor, each with a definition. | done |
| R3 | `checklist=None` or `[]` injects the default checklist (correctness, security, edge cases, error handling, duplication). | done |
| R4 | A custom non-empty `checklist` is used verbatim and the default is NOT appended. | done |
| R5 | `context` is included when provided and omitted when `None`. | done |
| R6 | The raw diff is embedded verbatim in the prompt. | done |
| R7 | The prompt surfaces a per-file blast-radius summary. | done |
| R8 | `parse_diff` returns `[{file, added_lines, removed_lines}]` per file. | done |
| R9 | `parse_diff` excludes `---`/`+++`/`@@`/`diff --git` file/hunk header lines from counts; lines inside a hunk (length from the `@@` header) are always counted, even when they look like headers. | done |
| R10 | `parse_diff` handles multi-file diffs, added-only files, and deletions to `/dev/null`. | done |
| R11 | `parse_diff` returns `[]` for empty / `None` / header-less input. | done |
| R12 | No network, no third-party imports in the core helper. | done |

## Interface contract

```python
def build_review_prompt(
    diff: str,
    context: str | None = None,
    checklist: list[str] | None = None,
) -> str:
    """Return a fresh-context adversarial review prompt string.

    Always includes: the disavowal line, the critical/major/minor severity
    rubric with definitions, a review checklist (default when `checklist`
    is falsy), a parsed changed-file summary, and the verbatim diff.
    """

def parse_diff(diff_text: str | None) -> list[dict]:
    """Parse a unified diff.

    Returns a list (first-seen file order) of:
        {"file": str, "added_lines": int, "removed_lines": int}
    Header/hunk lines are never counted. Non-diff or empty input -> [].
    """
```

### Constants

- `ADVERSARIAL_DISAVOWAL: str` — `"You did NOT write this code. Review it adversarially."`
- `DEFAULT_CHECKLIST: list[str]` — five default dimensions.
- `SEVERITY_RUBRIC: list[dict]` — `{level, definition}` for critical/major/minor.

## Out of scope

- Actually running a model / spawning the reviewer (orchestration lives with
  the host agent per `SKILL.md`).
- Git operations or fetching diffs.
- Persisting review history.
