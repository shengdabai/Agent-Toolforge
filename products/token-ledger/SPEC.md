# token-ledger — Specification

## Problem
LLM/agent billing dashboards report a single aggregate dollar figure but give no
explanation of *why* the bill is what it is. Operators cannot answer: which
session, which model, or which tagged workload drove cost; or whether a spike is
normal variance or an anomaly. `token-ledger` re-derives per-event cost from raw
token counts and a pricing table, then attributes and detects spikes.

## Scope
Pure-Python (stdlib only) cost reconstruction and attribution core, plus a thin
MCP server wrapper exposing the attribution as a tool.

## Data Contracts

### Pricing table
```
PRICING = {
    "<model-name>": {"input": <usd_per_1k_input_tokens>, "output": <usd_per_1k_output_tokens>},
    ...
}
```
Prices are USD per **1,000** tokens. Callers may pass an override mapping.

### Event
```
{
    "model": str,
    "input_tokens": int,
    "output_tokens": int,
    # optional grouping keys:
    "session": str,      # session id
    "tag": str,          # arbitrary workload tag
}
```
Missing token counts default to 0. Missing grouping keys default to "unknown".

## Interface Contracts

### cost(event, pricing=PRICING) -> float
- Returns USD cost of a single event:
  `(input_tokens/1000)*input_rate + (output_tokens/1000)*output_rate`.
- Unknown model or incomplete/non-finite/negative pricing => `ValueError`. Both directions must be supplied explicitly; intentional zero rates are allowed. Attribution propagates pricing errors rather than publishing partial totals.
- Missing/None token fields treated as 0.
- Result rounded to 10 decimal places to avoid float noise.

### attribute(events, by="session", pricing=PRICING) -> list[dict]
- Groups events by the key named in `by` (one of "session", "model", "tag").
- Each group dict:
  `{"key": <group value>, "cost": <usd>, "input_tokens": int, "output_tokens": int, "events": int}`
- Sorted by `cost` descending (ties broken by `key` ascending for determinism).
- Empty input => `[]`.
- Events missing the grouping key are bucketed under "unknown".

### detect_spikes(series, z=2.0) -> list[dict]
- `series`: list of `{"key": str, "cost": float}` (e.g. per-session cost series).
- Computes population mean and population standard deviation of `cost`.
- Flags any point whose cost exceeds `mean + z*stddev` as a spike.
- Each returned dict: `{"key", "cost", "z_score", "spike": True}` for flagged points only.
- stddev == 0 (all equal) or fewer than 2 points => no spikes => `[]`.
- Empty input => `[]`.

## MCP Tool
`attribute_cost(events: list, by: str = "session") -> list[dict]`
Thin wrapper over `attribute` using default `PRICING`.

## Open Questions (filled-in defaults)
- Q: Group-key for events lacking the field? **A: "unknown".**
- Q: stddev type? **A: population (N), not sample (N-1), for stable small series.**
- Q: Spike threshold inclusive? **A: strictly greater than `mean + z*stddev`.**
