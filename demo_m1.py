"""Demo de Módulo 1: Exchange Configuration & Filter Validation.

Flujo:
    1. Carga chimuelo.yaml y muestra la configuración activa.
    2. Parsea el fixture local de SOLUSDT (sin red) para mostrar los filtros.
    3. Demuestra validación de precio, cantidad y notional.
    4. Demuestra redondeo ROUND_DOWN para precio y cantidad.

Ejecutar:
    python demo_m1.py
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from chimuelo_prime.exchange_config import (
    BinancePublicClient,
    ExchangeConfigService,
    FilterValidationError,
    configure_logging,
    load_config,
)

_CONFIG_PATH = Path("config/chimuelo.yaml")
_FIXTURE_PATH = Path("tests/exchange_config/fixtures/exchange_info_solusdt.json")

SEP = "=" * 52


def _section(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def main() -> None:
    # ------------------------------------------------------------------ #
    # 1. Configuración
    # ------------------------------------------------------------------ #
    _section("1. Configuración (chimuelo.yaml)")

    config = load_config(_CONFIG_PATH)
    configure_logging(level=config.logging.level, fmt="console")

    print(f"  Entorno activo : {config.active_environment}")
    print(f"  Base URL       : {config.active_env.base_url}")
    print(f"  Timeout HTTP   : {config.active_env.http_timeout_seconds}s")
    print(f"  Símbolos       : {config.symbols}")
    print(f"  Log level      : {config.logging.level}")

    # ------------------------------------------------------------------ #
    # 2. Filtros desde fixture local (sin red)
    # ------------------------------------------------------------------ #
    _section("2. Filtros SOLUSDT (fixture local)")

    fixture_data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))

    client = BinancePublicClient(
        base_url=config.active_env.base_url,
        timeout=config.active_env.http_timeout_seconds,
    )
    service = ExchangeConfigService(client)

    # Parsea directamente desde el dict del fixture (sin HTTP)
    symbol_data = service._find_symbol(fixture_data, "SOLUSDT")
    filters_indexed = service._index_filters(symbol_data, "SOLUSDT")
    filters = service._build_symbol_filters("SOLUSDT", filters_indexed)
    client.close()

    print(f"  Símbolo        : {filters.symbol}")
    print(f"  tick_size      : {filters.tick_size}")
    print(f"  min_price      : {filters.min_price}")
    print(f"  max_price      : {filters.max_price}")
    print(f"  step_size      : {filters.step_size}")
    print(f"  min_qty        : {filters.min_qty}")
    print(f"  max_qty        : {filters.max_qty}")
    print(f"  min_notional   : {filters.min_notional}")
    print(f"  pct_up         : {filters.pct_up}")
    print(f"  pct_down       : {filters.pct_down}")
    print(f"  Tipo tick_size : {type(filters.tick_size).__name__}  (cero floats)")

    # ------------------------------------------------------------------ #
    # 3. Validación de precio, cantidad y notional
    # ------------------------------------------------------------------ #
    _section("3. Validación de orden")

    cases = [
        ("Precio válido   ", Decimal("172.50"), Decimal("0.10"), True),
        ("Precio < min    ", Decimal("0.00"),   Decimal("0.10"), False),
        ("Notional < min  ", Decimal("172.50"), Decimal("0.01"), False),
        ("Tick inválido   ", Decimal("172.513"), Decimal("0.10"), False),
    ]

    for label, price, qty, _ in cases:
        try:
            filters.validate_price(price)
            filters.validate_quantity(qty)
            filters.validate_notional(price, qty)
            status = "VALIDA"
        except FilterValidationError as exc:
            status = f"RECHAZADA — {exc}"
        print(f"  {label}: price={price}, qty={qty} ->{status}")

    # ------------------------------------------------------------------ #
    # 4. Redondeo ROUND_DOWN
    # ------------------------------------------------------------------ #
    _section("4. Redondeo ROUND_DOWN")

    price_examples = [
        Decimal("172.537"),
        Decimal("172.000"),
        Decimal("99.999"),
    ]
    qty_examples = [
        Decimal("0.1234"),
        Decimal("1.0000"),
        Decimal("0.0050"),
    ]

    print("  Precios:")
    for p in price_examples:
        rounded = filters.round_price_to_tick(p)
        print(f"    {p}  -> {rounded}")

    print("  Cantidades:")
    for q in qty_examples:
        rounded = filters.round_qty_to_step(q)
        print(f"    {q}  -> {rounded}")

    print(f"\n{SEP}")
    print("  M1 listo. Todos los filtros validados.")
    print(SEP)


if __name__ == "__main__":
    main()
