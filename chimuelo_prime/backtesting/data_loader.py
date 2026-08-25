"""Cargador y descargador de datos históricos de Binance para backtesting.

Responsabilidades:
    - Descargar Klines (velas) desde el API público de Binance.
    - Soportar paginación automática en chunks (límite de 1000 velas por petición).
    - Persistir un caché local en JSON en `data/cache/` para evitar re-descargas.
    - Retornar modelos Pydantic congelados (`HistoricalCandle`) con tipos `Decimal`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel, ConfigDict, Field

from chimuelo_prime.exchange_config.exceptions import ExchangeUnreachableError
from chimuelo_prime.exchange_config.logger import get_logger


class HistoricalCandle(BaseModel):
    """Representación inmutable de una vela histórica para backtesting.

    Garantiza consistencia Decimal y tipado estricto en la simulación.
    """

    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(description="Fecha y hora de apertura de la vela (UTC naive)")
    open: Decimal = Field(description="Precio de apertura")
    high: Decimal = Field(description="Precio máximo")
    low: Decimal = Field(description="Precio mínimo")
    close: Decimal = Field(description="Precio de cierre")
    volume: Decimal = Field(description="Volumen operado en activo base")


class HistoricalDataLoader:
    """Gestor de datos históricos con caché en disco local.

    Args:
        base_url: URL base de la API pública de Binance (inyectada para tests).
        timeout: Timeout para las peticiones HTTP en segundos.
        cache_dir: Carpeta donde se almacenará el caché local de Klines.
    """

    def __init__(
        self,
        base_url: str = "https://api.binance.com",
        timeout: int = 10,
        cache_dir: str = "data/cache",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._cache_dir = Path(cache_dir)
        self._log = get_logger(__name__)

    def get_candles(
        self,
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime,
        force_download: bool = False,
    ) -> list[HistoricalCandle]:
        """Obtiene velas históricas filtradas por rango de fecha.

        Intenta cargar desde el caché local en disco. Si no existe o no cubre
        el rango completo, descarga los datos desde Binance, los actualiza en caché
        y los retorna.

        Args:
            symbol: Símbolo de trading, ej. "SOLUSDT".
            interval: Intervalo de velas, ej. "1h", "1d".
            start_time: Fecha de inicio UTC naive.
            end_time: Fecha de fin UTC naive.
            force_download: Ignora el caché local y descarga todo de nuevo.

        Returns:
            Lista ordenada cronológicamente de `HistoricalCandle`.
        """
        symbol = symbol.upper()
        cache_file = self._cache_dir / f"{symbol}_{interval}.json"

        cached_raw: list[list[Any]] = []
        if not force_download and cache_file.exists():
            try:
                with open(cache_file, encoding="utf-8") as f:
                    cached_raw = json.load(f)
                self._log.info(
                    "backtest.cache_loaded",
                    symbol=symbol,
                    interval=interval,
                    records=len(cached_raw),
                )
            except Exception as exc:
                self._log.warning(
                    "backtest.cache_read_failed", file=str(cache_file), error=str(exc)
                )

        start_ms = int(start_time.replace(tzinfo=UTC).timestamp() * 1000)
        end_ms = int(end_time.replace(tzinfo=UTC).timestamp() * 1000)

        # Determinar si necesitamos descargar
        needs_download = force_download or not cached_raw
        if cached_raw and not force_download:
            first_ms = int(cached_raw[0][0])
            last_ms = int(cached_raw[-1][0])
            # Si el caché está completamente fuera del rango solicitado, descargar de nuevo
            if last_ms < start_ms or first_ms > end_ms:
                needs_download = True

        if needs_download:
            raw_klines = self._download_klines(symbol, interval, start_time, end_time)
            # Guardar en caché
            try:
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(raw_klines, f)
                self._log.info("backtest.cache_saved", symbol=symbol, file=str(cache_file))
            except Exception as exc:
                self._log.error("backtest.cache_write_failed", file=str(cache_file), error=str(exc))
            cached_raw = raw_klines

        # Filtrar y parsear las velas del caché que correspondan al rango start_time/end_time
        candles: list[HistoricalCandle] = []
        start_ms = int(start_time.replace(tzinfo=UTC).timestamp() * 1000)
        end_ms = int(end_time.replace(tzinfo=UTC).timestamp() * 1000)

        for item in cached_raw:
            open_time_ms = int(item[0])
            if start_ms <= open_time_ms <= end_ms:
                # Binance open_time es UTC en ms
                dt = datetime.fromtimestamp(open_time_ms / 1000, tz=UTC).replace(tzinfo=None)
                candles.append(
                    HistoricalCandle(
                        timestamp=dt,
                        open=Decimal(str(item[1])),
                        high=Decimal(str(item[2])),
                        low=Decimal(str(item[3])),
                        close=Decimal(str(item[4])),
                        volume=Decimal(str(item[5])),
                    )
                )

        # Ordenar cronológicamente
        candles.sort(key=lambda c: c.timestamp)
        self._log.info(
            "backtest.candles_ready",
            symbol=symbol,
            requested_range=f"{start_time} to {end_time}",
            returned_candles=len(candles),
        )
        return candles

    def _download_klines(
        self,
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[list[Any]]:
        """Descarga Klines históricos en chunks paginados desde Binance público.

        Llama a `GET /api/v3/klines` recursivamente usando el timestamp de cierre
        del último chunk como punto de partida.

        Raises:
            ExchangeUnreachableError: si hay timeout, error de red o HTTP >= 400.
        """
        url = f"{self._base_url}/api/v3/klines"
        all_klines: list[list[Any]] = []

        # Convertir datetimes a ms
        current_start_ms = int(start_time.replace(tzinfo=UTC).timestamp() * 1000)
        end_ms = int(end_time.replace(tzinfo=UTC).timestamp() * 1000)

        self._log.info(
            "backtest.download_started",
            symbol=symbol,
            interval=interval,
            start=start_time,
            end=end_time,
        )

        session = requests.Session()
        while current_start_ms <= end_ms:
            params: dict[str, str | int] = {
                "symbol": symbol,
                "interval": interval,
                "startTime": current_start_ms,
                "endTime": end_ms,
                "limit": 1000,
            }
            try:
                response = session.get(url, params=params, timeout=self._timeout)
                response.raise_for_status()
            except requests.exceptions.Timeout as exc:
                raise ExchangeUnreachableError(
                    f"Timeout ({self._timeout}s) descargando Klines de {symbol}"
                ) from exc
            except requests.exceptions.RequestException as exc:
                raise ExchangeUnreachableError(
                    f"Error de red descargando Klines de {symbol}: {exc}"
                ) from exc

            data = response.json()
            if not isinstance(data, list) or not data:
                break

            all_klines.extend(data)
            # El siguiente startTime es el closeTime de la última vela recibida + 1ms
            last_close_time = int(data[-1][6])
            current_start_ms = last_close_time + 1

            self._log.debug(
                "backtest.download_chunk",
                symbol=symbol,
                chunk_size=len(data),
                next_start_ms=current_start_ms,
            )

            # Evitar thundering herd en llamadas muy masivas
            if len(data) < 1000:
                break

        session.close()
        self._log.info("backtest.download_completed", symbol=symbol, total_records=len(all_klines))
        return all_klines
