"""List prices in USD per million tokens (input, output), checked 2026-10-03 against the
providers' published prices. USD per million tokens equals micro-USD per token, so a
call's cost in micro-USD is tokens_in * input + tokens_out * output."""

PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "gpt-6-luna": (0.10, 0.50),
    "gpt-6.1-sol": (2.00, 10.00),
    "gpt-6-astra": (10.00, 50.00),
}


def cost_micro_usd(model: str, tokens_in: int, tokens_out: int) -> int:
    """Unknown models are priced at the most expensive listed rate, never at zero."""
    key = next((k for k in PRICES if model == k or model.startswith(k + "-")), None)
    price_in, price_out = PRICES[key] if key else max(PRICES.values())
    return round(tokens_in * price_in + tokens_out * price_out)
