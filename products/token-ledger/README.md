# token-ledger

Token-bill traceability and cost attribution for AI agents. Your provider
dashboard tells you the total; `token-ledger` tells you **why**: which session,
which model, and which tagged workload drove the spend — and whether a jump is
an anomaly or normal variance.

## Why
Aggregate billing numbers are unactionable. To control LLM spend you need
per-event cost re-derived from raw token counts and a pricing table, rolled up
by the dimension you care about, with statistical spike detection on top.

## Install
No third-party dependencies are required for the core. Python 3.8+.

```bash
git clone <repo> && cd token-ledger
python3 -m unittest discover -s tests -p 'test_*.py'   # runs immediately
```

To run the optional MCP server:

```bash
pip install mcp   # only needed for server.py; core works without it
```

## Usage (core library)

```python
from ledger import PRICING, cost, attribute, detect_spikes

events = [
    {"model": "model-large", "input_tokens": 12000, "output_tokens": 3000,
     "session": "abc", "tag": "code-review"},
    {"model": "model-small", "input_tokens": 500, "output_tokens": 200,
     "session": "abc", "tag": "chat"},
]

cost(events[0])                       # -> USD cost of one event
attribute(events, by="session")       # -> [{key, cost, input_tokens, output_tokens, events}, ...]
attribute(events, by="model")         # group by model instead
attribute(events, by="tag")           # group by workload tag

# Per-session cost series -> flag anomalies > mean + z*stddev
series = [{"key": s["key"], "cost": s["cost"]} for s in attribute(events, by="session")]
detect_spikes(series, z=2.0)
```

### Custom pricing
The bundled `PRICING` table (`model-small`, `model-medium`, `model-large`,
`embed-small`) holds **placeholder, illustrative rates**, not any provider's real
prices; pass your own table for real numbers. Prices are USD per 1,000 tokens.
Override the table per call:

```python
my_pricing = {"my-model": {"input": 0.002, "output": 0.008}}
cost({"model": "my-model", "input_tokens": 1000, "output_tokens": 1000}, my_pricing)
```

Unknown models (including a missing `model` field) or incomplete/non-finite/negative rates raise `ValueError`, so one unpriced event makes the whole `attribute()` / `event_cost` call fail rather than being counted as zero; provide explicit input and output rates (zero is allowed when intentional). Missing, `None`, non-numeric or negative token fields are treated as 0. Events with no `by` key are grouped under `"unknown"`. The MCP tool reports this as an error, never a fabricated zero-cost result.

## MCP tools
`server.py` exposes the core as MCP tools via FastMCP:

- `attribute_cost(events, by="session")` — grouped cost attribution.
- `event_cost(event)` — cost of one event.
- `find_spikes(series, z=2.0)` — anomaly detection over a cost series.

```bash
python3 src/server.py
```

## Test
```bash
python3 -m unittest discover -s tests -p 'test_*.py'
# or simply
python3 -m unittest
```

All core tests use only the Python standard library (`unittest`); no network,
no optional packages.

## Layout
```
token-ledger/
├── SPEC.md          # requirements + interface contracts
├── README.md
├── src/
│   ├── ledger.py    # pure-stdlib core (cost / attribute / detect_spikes)
│   └── server.py    # thin MCP wrapper (optional mcp dependency)
└── tests/
    └── test_ledger.py
```

## 已知限制 (known limitations)

- **`detect_spikes` needs a reasonably long series.** It flags points above
  `mean + z*stddev` using the population standard deviation, so with `n` points
  the largest possible z-score is `sqrt(n-1)`. With the default `z=2.0`, a
  series of 5 or fewer points can never produce a spike (even `[1, 1, 1, 1, 1000]`
  returns `[]`); at `n=6` a single extreme point is flagged. Fewer than 2 points,
  or all-equal costs, also return `[]`. An empty result therefore does not prove
  there is no anomaly on short series.
- `detect_spikes` is not given pricing: it trusts the `cost` values you pass in
  the series (missing `cost` counts as 0).
