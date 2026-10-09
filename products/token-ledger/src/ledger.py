"""token-ledger core: re-derive per-event LLM cost, attribute it, detect spikes.

Pure stdlib. No network, no third-party deps. All prices are USD per 1,000
tokens. See SPEC.md for the full data and interface contracts.
"""
from __future__ import annotations

import math
from typing import Dict, List, Mapping, Sequence

# Placeholder pricing table (USD per 1,000 tokens). Override by passing your
# own mapping to cost()/attribute(). Values are illustrative, not authoritative.
PRICING: Dict[str, Dict[str, float]] = {
    "model-small": {"input": 0.0005, "output": 0.0015},
    "model-medium": {"input": 0.003, "output": 0.015},
    "model-large": {"input": 0.015, "output": 0.075},
    "embed-small": {"input": 0.0001, "output": 0.0000},
}

_UNKNOWN = "unknown"
_ROUND = 10


def _as_int(value) -> int:
    """Coerce a token field to a non-negative int, treating None/missing as 0."""
    if value is None:
        return 0
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else (0 if n < 0 else n)


def cost(event: Mapping, pricing: Mapping = PRICING) -> float:
    """USD cost of a single {model, input_tokens, output_tokens} event.

    Unknown model or invalid pricing raises ValueError; never report an unknown cost as zero.
    Missing/None token fields are treated as 0.
    """
    model = event.get("model")
    if model is None or model not in pricing:
        raise ValueError("Pricing unavailable for model: {}".format(model))
    rates = pricing[model]
    if "input" not in rates or "output" not in rates:
        raise ValueError("Incomplete pricing for model: {}".format(model))
    in_rate = float(rates["input"])
    out_rate = float(rates["output"])
    if not all(math.isfinite(rate) and rate >= 0 for rate in (in_rate, out_rate)):
        raise ValueError("Pricing must contain finite non-negative rates")

    in_tokens = _as_int(event.get("input_tokens"))
    out_tokens = _as_int(event.get("output_tokens"))

    total = (in_tokens / 1000.0) * in_rate + (out_tokens / 1000.0) * out_rate
    return round(total, _ROUND)


def attribute(
    events: Sequence[Mapping],
    by: str = "session",
    pricing: Mapping = PRICING,
) -> List[Dict]:
    """Group events by `by` ("session"|"model"|"tag") and sum cost + tokens.

    Returns a list of group dicts sorted by cost descending, ties broken by
    key ascending. Empty input -> []. Events missing the key -> "unknown".
    """
    if not events:
        return []

    buckets: Dict[str, Dict] = {}
    for event in events:
        key = event.get(by)
        key = str(key) if key not in (None, "") else _UNKNOWN
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "key": key,
                "cost": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "events": 0,
            }
            buckets[key] = bucket
        bucket["cost"] = round(bucket["cost"] + cost(event, pricing), _ROUND)
        bucket["input_tokens"] += _as_int(event.get("input_tokens"))
        bucket["output_tokens"] += _as_int(event.get("output_tokens"))
        bucket["events"] += 1

    return sorted(buckets.values(), key=lambda b: (-b["cost"], b["key"]))


def detect_spikes(series: Sequence[Mapping], z: float = 2.0) -> List[Dict]:
    """Flag points whose cost exceeds mean + z*stddev (population stddev).

    `series`: list of {"key", "cost"}. Fewer than 2 points, or stddev == 0,
    yields no spikes. Empty input -> []. Returns only flagged points as
    {"key", "cost", "z_score", "spike": True}.
    """
    if not series or len(series) < 2:
        return []

    costs = [float(p.get("cost", 0.0)) for p in series]
    mean = sum(costs) / len(costs)
    variance = sum((c - mean) ** 2 for c in costs) / len(costs)
    stddev = math.sqrt(variance)
    if stddev == 0:
        return []

    threshold = mean + z * stddev
    spikes: List[Dict] = []
    for point, c in zip(series, costs):
        if c > threshold:
            spikes.append(
                {
                    "key": point.get("key"),
                    "cost": c,
                    "z_score": round((c - mean) / stddev, _ROUND),
                    "spike": True,
                }
            )
    return spikes
