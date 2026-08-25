"""Tests unitarios para el cargador de datos históricos de backtesting (M6)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import responses

from chimuelo_prime.backtesting.data_loader import HistoricalCandle, HistoricalDataLoader
from chimuelo_prime.exchange_config.exceptions import ExchangeUnreachableError


@pytest.fixture
def mock_klines_data() -> list[list[float | str]]:
    """Fixture que retorna una vela mockeada de Binance."""
    return [
        [
            1715644800000,  # Open time (ms) - 2024-05-14T00:00:00Z
            "145.50",  # Open
            "147.20",  # High
            "144.10",  # Low
            "146.80",  # Close
            "12000.50",  # Volume
            1715648399999,  # Close time
            "1746072.50",  # Quote asset volume
            150,  # Number of trades
            "6000.25",  # Taker buy base asset volume
            "873036.25",  # Taker buy quote asset volume
            "0",  # Ignore
        ]
    ]


def test_data_loader_downloads_and_caches_candles(
    tmp_path: Path, mock_klines_data: list[list[float | str]]
) -> None:
    """Verifica que el cargador descargue datos, los parsee a Decimal y cree la caché."""
    cache_dir = tmp_path / "cache"
    loader = HistoricalDataLoader(base_url="https://mock-binance.com", cache_dir=str(cache_dir))

    symbol = "SOLUSDT"
    interval = "1h"
    start_time = datetime(2024, 5, 14, 0, 0, tzinfo=UTC).replace(tzinfo=None)
    end_time = datetime(2024, 5, 14, 1, 0, tzinfo=UTC).replace(tzinfo=None)

    # Configurar mock de responses
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            "https://mock-binance.com/api/v3/klines",
            json=mock_klines_data,
            status=200,
        )

        candles = loader.get_candles(symbol, interval, start_time, end_time)

    # Validaciones del resultado
    assert len(candles) == 1
    candle = candles[0]
    assert isinstance(candle, HistoricalCandle)
    assert candle.timestamp == datetime(2024, 5, 14, 0, 0)
    assert candle.open == Decimal("145.50")
    assert candle.high == Decimal("147.20")
    assert candle.low == Decimal("144.10")
    assert candle.close == Decimal("146.80")
    assert candle.volume == Decimal("12000.50")

    # Verificar que el archivo de caché se haya creado
    cache_file = cache_dir / f"{symbol}_{interval}.json"
    assert cache_file.exists()

    # Cargar y verificar el contenido del caché
    with open(cache_file, encoding="utf-8") as f:
        cached_data = json.load(f)
    assert cached_data == mock_klines_data


def test_data_loader_uses_cache_if_present(
    tmp_path: Path, mock_klines_data: list[list[float | str]]
) -> None:
    """Verifica que si la caché ya existe, no se llame a la API de Binance."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True)
    symbol = "SOLUSDT"
    interval = "1h"
    cache_file = cache_dir / f"{symbol}_{interval}.json"

    # Escribir previamente en caché
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(mock_klines_data, f)

    loader = HistoricalDataLoader(base_url="https://mock-binance.com", cache_dir=str(cache_dir))

    start_time = datetime(2024, 5, 14, 0, 0, tzinfo=UTC).replace(tzinfo=None)
    end_time = datetime(2024, 5, 14, 1, 0, tzinfo=UTC).replace(tzinfo=None)

    # Si intentara conectarse a la API sin mock fallaría, demostrando que lee del caché
    candles = loader.get_candles(symbol, interval, start_time, end_time)

    assert len(candles) == 1
    assert candles[0].close == Decimal("146.80")


def test_data_loader_raises_unreachable_on_network_error() -> None:
    """Verifica que lance ExchangeUnreachableError en caso de fallo de red o timeout."""
    loader = HistoricalDataLoader(base_url="https://mock-binance.com", cache_dir="data/cache")

    symbol = "SOLUSDT"
    interval = "1h"
    start_time = datetime(2024, 5, 14, 0, 0)
    end_time = datetime(2024, 5, 14, 1, 0)

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            "https://mock-binance.com/api/v3/klines",
            status=500,
        )

        with pytest.raises(ExchangeUnreachableError):
            loader.get_candles(symbol, interval, start_time, end_time, force_download=True)
