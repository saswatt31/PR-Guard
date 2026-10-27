"""Token pricing for cost accounting.

Prices are USD per one million tokens and are estimates. They are configuration-like
data, not billing truth; the exact provider dashboard remains authoritative.
"""

from __future__ import annotations

# (input per 1M, output per 1M)
PRICES: dict[str, tuple[float, float]] = {
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "fake": (0.0, 0.0),
}
DEFAULT_PRICE = (0.0, 0.0)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    input_price, output_price = PRICES.get(model, DEFAULT_PRICE)
    return (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
