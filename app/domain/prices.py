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


# Prompt-cache rates as multiples of the input price (BD-30): Claude bills cache reads at
# 0.1 times and 5-minute cache writes at 1.25 times the input rate. OpenAI's cached-input
# rates for these models are not confirmed, so cached tokens are billed at the full input
# rate (owner, 2026-10-04): the cap can never undercount.
CACHE_RATES: dict[str, tuple[float, float]] = {"claude-": (0.1, 1.25)}
# Embedding models, USD per million input tokens; local models cost nothing
EMBEDDING_PRICES: dict[str, float] = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
}


def cost_micro_usd(
    model: str,
    tokens_in: int,
    tokens_out: int,
    cached_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> int:
    """`tokens_in` counts every input token, cached and written ones included. Unknown
    models are priced at the most expensive listed rate, never at zero."""
    key = next((k for k in PRICES if model == k or model.startswith(k + "-")), None)
    price_in, price_out = PRICES[key] if key else max(PRICES.values())
    read, write = next((r for p, r in CACHE_RATES.items() if model.startswith(p)), (1.0, 1.0))
    plain = max(tokens_in - cached_tokens - cache_write_tokens, 0)
    billed_in = plain + cached_tokens * read + cache_write_tokens * write
    return round(billed_in * price_in + tokens_out * price_out)


def embedding_cost_micro_usd(model: str, tokens: int) -> int:
    """Hosted embedding models by their rate; a model not listed is a local one (free)."""
    return round(tokens * EMBEDDING_PRICES.get(model, 0.0))
