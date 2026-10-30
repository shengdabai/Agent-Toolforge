---
name: fresh-eyes-review
description: "Spawn an independent fresh-context reviewer to adversarially audit code this session just wrote, instead of letting the author self-approve. Use when the user asks for an independent, adversarial or code review, says \"fresh eyes\", \"second pair of eyes\", \"review your own changes\" or \"don't self-approve\", or before merging a non-trivial diff. Builds the reviewer prompt from the diff and grades blast radius and severity (critical/major/minor)."
---

# Fresh Eyes Review

## Why this exists

An agent that reviews its own code in the same context almost always approves
it: it remembers the intent, fills gaps charitably, and never re-derives
whether the code is actually correct. That is not a review — it is a
signature. This skill forces a **fresh, adversarial context** so the reviewer
treats the diff as hostile code written by someone else.

## Iron rule: the reviewer is NOT the author

Never review a diff in the same context that produced it. Always derive a new
reviewer context that:

1. Has no memory of writing the code and no stake in approving it.
2. Opens with: **"You did NOT write this code. Review it adversarially."**
3. Assumes the code is wrong until the diff proves otherwise.
4. Cites `file:line` for every finding and proposes a concrete fix.

## Protocol

### 1. Get the diff

Collect the unified diff under review (e.g. `git diff`, `git diff --cached`,
or a PR patch). Keep it verbatim — do not summarize it.

### 2. Build the reviewer prompt with the helper

Use the stdlib helper so the prompt always carries the disavowal line, the
severity rubric, the default checklist, and a parsed blast-radius summary:

```python
import sys; sys.path.insert(0, "src")
from review import build_review_prompt, parse_diff

summary = parse_diff(diff_text)          # [{file, added_lines, removed_lines}]
prompt = build_review_prompt(
    diff_text,
    context="Payments service; PCI scope; Python 3.13.",  # optional
    checklist=None,                                        # None => default
)
```

`parse_diff` counts by hunk length (from the `@@ -a,b +c,d @@` headers), so removed
lines that look like headers (e.g. `--- old comment`) are counted correctly;
truncated diffs (for example a `---` header with no `+++`) are the known weak
spot, so check the summary against the diff when it matters.

The default checklist covers **correctness, security, edge cases, error
handling, duplication**. Pass a custom `checklist=[...]` only to add
domain-specific dimensions (e.g. "race conditions", "i18n").

### 3. Run the review in a SEPARATE context

Hand `prompt` to a **fresh** reviewer — a separate sub-agent / new session /
different model. Do NOT answer it from the authoring context. The whole point
is independence.

### 4. Grade by severity

The reviewer rates every finding:

- **CRITICAL** — correctness, security, or data-loss defect. Blocks merge.
- **MAJOR** — significant bug, missing edge case, risky design. Blocks merge
  unless explicitly justified.
- **MINOR** — style, naming, small duplication. Does not block.

### 5. Verdict gate

APPROVE only when there are **zero CRITICAL and zero MAJOR** findings.
Otherwise REQUEST CHANGES and loop: fix, then re-run a fresh review on the new
diff. Never let the author cast the deciding vote.

## Anti-patterns

- Reviewing in the authoring context "to save a round trip" — defeats the
  whole skill.
- Trimming the diff before review — the reviewer must see the actual lines.
- Auto-approving because tests pass — tests catch what they were written to
  catch; the adversarial pass catches what they missed.

## Files

- `src/review.py` — `build_review_prompt(diff, context, checklist)` and
  `parse_diff(diff_text)`. Stdlib only.
- `tests/test_review.py` — `python3 -m unittest discover -s tests -p 'test_*.py'`.
