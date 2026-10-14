"""List prices in USD per million tokens (input, output), checked 2026-10-03 against the
providers' published prices; the OpenAI models of the free data-sharing allowance were
added 2026-10-14 from developers.openai.com/api/docs/pricing (E-02, BD-55). They are
priced at the list rate even when the daily allowance covers them, so a run past the
allowance is still capped at its true cost. USD per million tokens equals micro-USD per token, so a
call's cost in micro-USD is tokens_in * input + tokens_out * output."""

PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "gpt-6-luna": (0.10, 0.50),
    "gpt-6.1-sol": (2.00, 10.00),
    "gpt-6-astra": (10.00, 50.00),
    # OpenAI's complimentary data-sharing allowance (E-02, BD-55): larger models
    "gpt-5.4": (2.50, 15.00),  # under 272K tokens of context
    "gpt-5.2": (1.75, 14.00),
    "gpt-5.1": (1.25, 10.00),
    "gpt-5": (1.25, 10.00),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o": (2.50, 10.00),
    "o3": (2.00, 8.00),
    # ... and smaller models
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o-mini": (0.15, 0.60),
    "o3-mini": (1.10, 4.40),
    "o4-mini": (1.10, 4.40),
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
    models are priced at the most expensive listed rate, never at zero. The longest
    listed name wins, so `gpt-5-mini-2025-08-07` is `gpt-5-mini`, not `gpt-5` (E-02)."""
    matches = [k for k in PRICES if model == k or model.startswith(k + "-")]
    key = max(matches, key=len) if matches else None
    price_in, price_out = PRICES[key] if key else max(PRICES.values())
    read, write = next((r for p, r in CACHE_RATES.items() if model.startswith(p)), (1.0, 1.0))
    plain = max(tokens_in - cached_tokens - cache_write_tokens, 0)
    billed_in = plain + cached_tokens * read + cache_write_tokens * write
    return round(billed_in * price_in + tokens_out * price_out)


def embedding_cost_micro_usd(model: str, tokens: int) -> int:
    """Hosted embedding models by their rate; a model not listed is a local one (free)."""
    return round(tokens * EMBEDDING_PRICES.get(model, 0.0))
