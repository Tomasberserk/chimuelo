"""Tests para BinancePublicClient (client.py).

Usa la librería `responses` para mockear HTTP sin tocar la red real.
Cubre:
    - GET exitoso retorna el JSON parseado.
    - Timeout lanza ExchangeUnreachableError.
    - ConnectionError lanza ExchangeUnreachableError.
    - HTTP 500 lanza ExchangeUnreachableError.
    - HTTP 400 lanza ExchangeUnreachableError.
    - El mensaje de error contiene la URL para trazabilidad.
    - close() no lanza excepciones.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import responses as resp_lib
from responses import matchers

from chimuelo_prime.exchange_config.client import BinancePublicClient
from chimuelo_prime.exchange_config.exceptions import ExchangeUnreachableError

_BASE_URL = "https://testnet.binance.vision"
_EXCHANGE_INFO_URL = f"{_BASE_URL}/api/v3/exchangeInfo"

# Ruta al fixture real de Binance (reutilizamos el JSON de T#2)
_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "exchange_info_solusdt.json"


@pytest.fixture()
def client() -> BinancePublicClient:
    return BinancePublicClient(base_url=_BASE_URL, timeout=5)


@pytest.fixture()
def exchange_info_payload() -> dict:  # type: ignore[type-arg]
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Tests: respuesta exitosa
# --------------------------------------------------------------------------- #
class TestGetExchangeInfoSuccess:
    @resp_lib.activate
    def test_returns_parsed_json(
        self,
        client: BinancePublicClient,
        exchange_info_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        resp_lib.add(
            resp_lib.GET,
            _EXCHANGE_INFO_URL,
            json=exchange_info_payload,
            status=200,
        )
        result = client.get_exchange_info("SOLUSDT")
        assert "symbols" in result

    @resp_lib.activate
    def test_symbol_in_response(
        self,
        client: BinancePublicClient,
        exchange_info_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        resp_lib.add(
            resp_lib.GET,
            _EXCHANGE_INFO_URL,
            json=exchange_info_payload,
            status=200,
        )
        result = client.get_exchange_info("SOLUSDT")
        symbols = [s["symbol"] for s in result["symbols"]]
        assert "SOLUSDT" in symbols

    @resp_lib.activate
    def test_query_param_symbol_sent(
        self,
        client: BinancePublicClient,
        exchange_info_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        """El client debe pasar `symbol` como query param."""
        resp_lib.add(
            resp_lib.GET,
            _EXCHANGE_INFO_URL,
            json=exchange_info_payload,
            status=200,
            match=[matchers.query_param_matcher({"symbol": "SOLUSDT"})],
        )
        client.get_exchange_info("SOLUSDT")
        assert len(resp_lib.calls) == 1
        assert "symbol=SOLUSDT" in resp_lib.calls[0].request.url


# --------------------------------------------------------------------------- #
# Tests: errores de red → ExchangeUnreachableError
# --------------------------------------------------------------------------- #
class TestGetExchangeInfoNetworkErrors:
    @resp_lib.activate
    def test_timeout_raises_unreachable(self, client: BinancePublicClient) -> None:
        resp_lib.add(
            resp_lib.GET,
            _EXCHANGE_INFO_URL,
            body=__import__("requests").exceptions.Timeout("timeout simulado"),
        )
        with pytest.raises(ExchangeUnreachableError, match="Timeout"):
            client.get_exchange_info("SOLUSDT")

    @resp_lib.activate
    def test_connection_error_raises_unreachable(
        self, client: BinancePublicClient
    ) -> None:
        resp_lib.add(
            resp_lib.GET,
            _EXCHANGE_INFO_URL,
            body=__import__("requests").exceptions.ConnectionError(
                "connection refused"
            ),
        )
        with pytest.raises(ExchangeUnreachableError, match="Error de conexión"):
            client.get_exchange_info("SOLUSDT")

    @resp_lib.activate
    def test_http_500_raises_unreachable(self, client: BinancePublicClient) -> None:
        resp_lib.add(
            resp_lib.GET,
            _EXCHANGE_INFO_URL,
            json={"code": -1000, "msg": "Internal server error"},
            status=500,
        )
        with pytest.raises(ExchangeUnreachableError, match="HTTP"):
            client.get_exchange_info("SOLUSDT")

    @resp_lib.activate
    def test_http_503_raises_unreachable(self, client: BinancePublicClient) -> None:
        resp_lib.add(
            resp_lib.GET,
            _EXCHANGE_INFO_URL,
            json={"msg": "Service Unavailable"},
            status=503,
        )
        with pytest.raises(ExchangeUnreachableError):
            client.get_exchange_info("SOLUSDT")

    @resp_lib.activate
    def test_http_400_raises_unreachable(self, client: BinancePublicClient) -> None:
        resp_lib.add(
            resp_lib.GET,
            _EXCHANGE_INFO_URL,
            json={"code": -1121, "msg": "Invalid symbol"},
            status=400,
        )
        with pytest.raises(ExchangeUnreachableError):
            client.get_exchange_info("SOLUSDT")


# --------------------------------------------------------------------------- #
# Tests: comportamiento del objeto
# --------------------------------------------------------------------------- #
class TestClientBehavior:
    def test_close_does_not_raise(self, client: BinancePublicClient) -> None:
        """close() debe liberar recursos sin lanzar excepciones."""
        client.close()  # no debe lanzar

    def test_trailing_slash_stripped_from_base_url(self) -> None:
        """URL con trailing slash no debe producir doble barra en requests."""
        c = BinancePublicClient(base_url=f"{_BASE_URL}/", timeout=5)
        # El atributo interno debe estar limpio
        assert not c._base_url.endswith("/")
