"""Per-token prices (USD per million tokens) for budget accounting. ADR 0004.

Source: Claude API reference (pricing cached 2026-11-03). Cache writes use the 5-minute TTL
(1.25x input). Batch requests are billed at 50%. Update here if prices change; every
``llm_usage`` row stores the computed cost, so history keeps the price in force at the time.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"


@dataclass(frozen=True)
class Price:
    input: Decimal
    output: Decimal
    cache_read: Decimal
    # Haiku 5.5 prices apply to prompts up to 100K tokens; above that, the higher tier.
    long_input: Decimal | None = None
    long_output: Decimal | None = None
    long_threshold: int = 100_000


PRICES: dict[str, Price] = {
    HAIKU: Price(
        input=Decimal("0.10"),
        output=Decimal("0.50"),
        cache_read=Decimal("0.01"),
        long_input=Decimal("0.50"),
        long_output=Decimal("2.50"),
    ),
    SONNET: Price(input=Decimal("2.00"), output=Decimal("10.00"), cache_read=Decimal("0.10")),
}

CACHE_WRITE_MULTIPLIER = Decimal("1.25")
BATCH_DISCOUNT = Decimal("0.5")
_MTOK = Decimal(1_000_000)


def cost_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
    batch: bool = False,
) -> Decimal:
    price = PRICES[model]
    prompt = input_tokens + cache_write_tokens + cache_read_tokens
    long = price.long_input is not None and prompt > price.long_threshold
    in_rate = price.long_input if long and price.long_input else price.input
    out_rate = price.long_output if long and price.long_output else price.output
    total = (
        Decimal(input_tokens) * in_rate
        + Decimal(cache_write_tokens) * in_rate * CACHE_WRITE_MULTIPLIER
        + Decimal(cache_read_tokens) * price.cache_read
        + Decimal(output_tokens) * out_rate
    ) / _MTOK
    if batch:
        total *= BATCH_DISCOUNT
    return total.quantize(Decimal("0.000001"))
