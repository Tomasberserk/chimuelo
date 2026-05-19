"""Tests para _internal/payload_builder.py — 100% de cobertura obligatoria.

Cubre:
    - Redondeo de precio al tick_size más cercano hacia abajo.
    - Redondeo de cantidad al step_size más cercano hacia abajo.
    - Todos los valores del dict retornado son str.
    - timeInForce siempre "GTC".
    - type siempre "LIMIT".
    - client_order_id incluido si se provee, ausente si None.
    - FilterValidationError si precio < min_price.
    - FilterValidationError si notional < min_notional.
    - build_cancel_payload retorna symbol y orderId como str.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from chimuelo_prime.exchange_config.exceptions import FilterValidationError
from chimuelo_prime.order_execution._internal.payload_builder import (
    build_cancel_payload,
    build_limit_order_payload,
)
from tests.order_execution.conftest import make_order_orm  # noqa: F401 (fixture dep)


class TestBuildLimitOrderPayload:
    def test_price_rounded_to_tick(self, symbol_config) -> None:
        price = Decimal("150.009")  # tick_size=0.01 → debe quedar 150.00
        qty = Decimal("0.10")
        payload = build_limit_order_payload(symbol_config, "BUY", price, qty, None)
        assert payload["price"] == str(Decimal("150.00"))

    def test_qty_rounded_to_step(self, symbol_config) -> None:
        price = Decimal("150.00")
        qty = Decimal("0.109")  # step_size=0.01 → debe quedar 0.10
        payload = build_limit_order_payload(symbol_config, "BUY", price, qty, None)
        assert payload["quantity"] == str(Decimal("0.10"))

    def test_all_values_are_str(self, symbol_config) -> None:
        payload = build_limit_order_payload(
            symbol_config, "BUY", Decimal("150.00"), Decimal("0.10"), None
        )
        for key, value in payload.items():
            assert isinstance(value, str), f"Campo '{key}' no es str: {type(value)}"

    def test_time_in_force_is_gtc(self, symbol_config) -> None:
        payload = build_limit_order_payload(
            symbol_config, "BUY", Decimal("150.00"), Decimal("0.10"), None
        )
        assert payload["timeInForce"] == "GTC"

    def test_type_is_limit(self, symbol_config) -> None:
        payload = build_limit_order_payload(
            symbol_config, "BUY", Decimal("150.00"), Decimal("0.10"), None
        )
        assert payload["type"] == "LIMIT"

    def test_client_order_id_included_when_provided(self, symbol_config) -> None:
        payload = build_limit_order_payload(
            symbol_config, "BUY", Decimal("150.00"), Decimal("0.10"), "my_cid"
        )
        assert payload["newClientOrderId"] == "my_cid"

    def test_client_order_id_absent_when_none(self, symbol_config) -> None:
        payload = build_limit_order_payload(
            symbol_config, "BUY", Decimal("150.00"), Decimal("0.10"), None
        )
        assert "newClientOrderId" not in payload

    def test_side_is_preserved(self, symbol_config) -> None:
        buy = build_limit_order_payload(symbol_config, "BUY", Decimal("150.00"), Decimal("0.10"), None)
        sell = build_limit_order_payload(symbol_config, "SELL", Decimal("150.00"), Decimal("0.10"), None)
        assert buy["side"] == "BUY"
        assert sell["side"] == "SELL"

    def test_symbol_from_config(self, symbol_config) -> None:
        payload = build_limit_order_payload(symbol_config, "BUY", Decimal("150.00"), Decimal("0.10"), None)
        assert payload["symbol"] == "SOLUSDT"

    def test_raises_filter_validation_if_price_below_min(self, symbol_config) -> None:
        with pytest.raises(FilterValidationError):
            build_limit_order_payload(
                symbol_config, "BUY", Decimal("0.001"), Decimal("0.10"), None
            )

    def test_raises_filter_validation_if_notional_below_min(self, symbol_config) -> None:
        # min_notional = 5.00; price=0.01, qty=0.01 → notional=0.0001
        with pytest.raises(FilterValidationError):
            build_limit_order_payload(
                symbol_config, "BUY", Decimal("0.01"), Decimal("0.01"), None
            )


class TestBuildCancelPayload:
    def test_symbol_is_str(self) -> None:
        payload = build_cancel_payload("SOLUSDT", 12345)
        assert isinstance(payload["symbol"], str)
        assert payload["symbol"] == "SOLUSDT"

    def test_order_id_is_str(self) -> None:
        payload = build_cancel_payload("SOLUSDT", 12345)
        assert isinstance(payload["orderId"], str)
        assert payload["orderId"] == "12345"

    def test_all_values_are_str(self) -> None:
        payload = build_cancel_payload("SOLUSDT", 99999)
        for value in payload.values():
            assert isinstance(value, str)
