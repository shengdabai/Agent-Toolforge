# fresh-eyes-review

An independent, fresh-context adversarial reviewer for AI coding agents.

## What it is

When an agent reviews the code it just wrote, in the same context, it almost
always approves it — it remembers the intent and never re-checks correctness.
`fresh-eyes-review` is a **skill** that forces a separate, adversarial review
pass: the reviewer is told *"You did NOT write this code. Review it
adversarially."* and grades every finding by severity (critical / major /
minor) before any merge.

## Form

A Claude/agent **skill**:

- `SKILL.md` — frontmatter with trigger words (independent review, code
  review, adversarial review, "don't self-approve", "fresh eyes") and the
  reviewer protocol.
- `src/review.py` — pure standard-library helper. No network, no third-party
  packages.
- `tests/test_review.py` — `unittest` suite.

## Install

Copy this directory into your agent's skills location, e.g.:

```
cp -r fresh-eyes-review <your-agent>/skills/fresh-eyes-review
```

No `pip install` required — the core helper is stdlib only.

## Usage (helper API)

```python
import sys
sys.path.insert(0, "src")
from review import build_review_prompt, parse_diff

diff = open("change.patch").read()

# Per-file blast radius: [{"file": ..., "added_lines": N, "removed_lines": M}]
summary = parse_diff(diff)

# Build a fresh-context adversarial review prompt.
prompt = build_review_prompt(
    diff,
    context="Payments service, PCI scope.",  # optional
    checklist=None,                           # None/[] => default checklist
)

# Hand `prompt` to a SEPARATE reviewer context (new session / sub-agent /
# different model). Never review in the authoring context.
```

The default checklist covers **correctness, security, edge cases, error
handling, duplication**. Pass `checklist=["race conditions", ...]` to use a
custom one verbatim.

`parse_diff` uses the `@@ -a,b +c,d @@` hunk headers to know how many lines
belong to each hunk. While a hunk is open every line is counted as content, so a
removed SQL comment (rendered `--- old comment`) or an added `++ x` is counted as
a removed/added line instead of being mistaken for a file header; `\ No newline
at end of file` is ignored. Outside a hunk, `diff --git`, `---`, `+++` and `@@`
lines are never counted. If a hunk header is malformed it falls back to
header-based counting, and a hunk that ends earlier than it declares (truncated
diff) is closed at the next non-content line such as `diff --git`.

Known limitations: in a truncated diff whose next file starts with a plain
`--- a/x` header (no `diff --git` line) that line may still be counted as one
removed line; `diff --git` lines whose paths contain spaces are not parsed.

### Verdict rule

APPROVE only when there are zero CRITICAL and zero MAJOR findings; otherwise
REQUEST CHANGES, fix, and re-run a fresh review on the new diff.

## Run the tests

```bash
cd fresh-eyes-review
python3 -m unittest discover -s tests -p 'test_*.py'
# or, verbose:
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Layout

```
fresh-eyes-review/
├── SKILL.md          # skill definition + reviewer protocol
├── SPEC.md           # requirements + interface contract
├── README.md
├── src/
│   └── review.py     # build_review_prompt(), parse_diff() — stdlib only
└── tests/
    └── test_review.py
```
