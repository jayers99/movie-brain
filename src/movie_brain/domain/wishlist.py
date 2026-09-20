"""The CheapCharts wishlist target rule (brief 2026-09-19-price-watch): the owner's own ruling is
the film's lowest price EVER plus one dollar — a low that happened exactly once still counts
(Do the Right Thing: $2.99 once, $4.99 thirty-two times → $3.99). No price is stored or shown;
the low is read at the moment of the click."""

from __future__ import annotations

from decimal import Decimal

TARGET_MARKUP = Decimal("1.00")


def target_price(low: Decimal) -> Decimal:
    return low + TARGET_MARKUP
