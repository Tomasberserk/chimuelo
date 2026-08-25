"""Tests unitarios e integrales para el Dashboard Server de FastAPI y WebSockets.

Cubre:
1. Endpoints REST de Klines con cálculo cuantitativo de EMA 200, EMA 20, RSI y ATR.
2. Endpoint REST de 24h Ticker de Binance.
3. Endpoints REST de ciclo de vida de Paper Trading (status, start, stop, trades).
4. WebSocket /ws/live con streaming de updates y protocolo ping/pong.
5. Rutas de archivos estáticos y Dashboard HTML.
6. Módulo CLI de lanzamiento run_dashboard.py.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests
from fastapi.testclient import TestClient

from chimuelo_prime.orchestrator.dashboard_server import (
    PaperTradingManager,
    app,
)
from run_dashboard import main as run_dashboard_main, print_banner


@pytest.fixture
def client() -> TestClient:
    """Cliente de pruebas para la API de FastAPI."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_paper_manager() -> None:
    """Asegura que el singleton PaperTradingManager esté limpio antes de cada test."""
    manager = PaperTradingManager.get_instance()
    manager.reset(Decimal("25.00"))


# ==============================================================================
# 1. PRUEBAS PARA /api/market/klines
# ==============================================================================


class TestMarketKlinesEndpoint:
    """Pruebas para el endpoint de velas Klines con indicadores precalculados."""

    def _generate_mock_klines(self, count: int = 210) -> list[list[Any]]:
        """Genera una serie sintética de velas en formato Binance."""
        base_time = 1700000000000
        klines = []
        for i in range(count):
            open_price = 100.0 + i * 0.5
            high_price = open_price + 2.0
            low_price = open_price - 1.0
            close_price = open_price + 0.8
            volume = 1000.0 + i * 10
            klines.append(
                [
                    base_time + (i * 3600000),  # Open time
                    f"{open_price:.2f}",        # Open
                    f"{high_price:.2f}",        # High
                    f"{low_price:.2f}",         # Low
                    f"{close_price:.2f}",       # Close
                    f"{volume:.2f}",            # Volume
                    base_time + ((i + 1) * 3600000) - 1,  # Close time
                    "50000.00",                 # Quote asset volume
                    100,                        # Number of trades
                    "500.00",                   # Taker buy base asset volume
                    "25000.00",                 # Taker buy quote asset volume
                    "0",                        # Ignore
                ]
            )
        return klines

    @patch("requests.get")
    def test_get_klines_success(self, mock_get: MagicMock, client: TestClient) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._generate_mock_klines(210)
        mock_get.return_value = mock_response

        res = client.get("/api/market/klines?symbol=SOLUSDT&interval=1h&limit=210")
        assert res.status_code == 200
        data = res.json()

        assert data["symbol"] == "SOLUSDT"
        assert data["interval"] == "1h"
        assert data["count"] == 210
        assert len(data["candles"]) == 210

        # Validar estructura de la primera vela
        first_candle = data["candles"][0]
        assert "time" in first_candle
        assert "open" in first_candle
        assert "high" in first_candle
        assert "low" in first_candle
        assert "close" in first_candle
        assert "volume" in first_candle
        assert first_candle["ema200"] is None  # Aún no hay 200 periodos

        # Validar cálculo de EMA 200 en las velas posteriores a 200
        last_candle = data["candles"][-1]
        assert last_candle["ema200"] is not None
        assert isinstance(last_candle["ema200"], float)
        assert last_candle["ema20"] is not None
        assert isinstance(last_candle["ema20"], float)
        assert last_candle["rsi"] is not None
        assert isinstance(last_candle["rsi"], float)
        assert last_candle["atr"] is not None
        assert isinstance(last_candle["atr"], float)

    @patch("requests.get")
    def test_get_klines_network_error_raises_502(
        self, mock_get: MagicMock, client: TestClient
    ) -> None:
        mock_get.side_effect = requests.exceptions.RequestException("Binance timeout")

        res = client.get("/api/market/klines?symbol=SOLUSDT&interval=1h&limit=200")
        assert res.status_code == 502
        assert "Binance timeout" in res.json()["detail"]

    @patch("requests.get")
    def test_get_klines_invalid_response_format_raises_502(
        self, mock_get: MagicMock, client: TestClient
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": -1121, "msg": "Invalid symbol"}
        mock_get.return_value = mock_response

        res = client.get("/api/market/klines?symbol=BADSYMBOL&interval=1h&limit=200")
        assert res.status_code == 502

    @patch("requests.get")
    def test_get_klines_corrupt_data_raises_502(
        self, mock_get: MagicMock, client: TestClient
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [["invalid", "corrupt"]]
        mock_get.return_value = mock_response

        res = client.get("/api/market/klines?symbol=SOLUSDT&interval=1h&limit=200")
        assert res.status_code == 502


# ==============================================================================
# 2. PRUEBAS PARA /api/market/ticker
# ==============================================================================


class TestMarketTickerEndpoint:
    """Pruebas para el endpoint de ticker 24hr de Binance."""

    @patch("requests.get")
    def test_get_ticker_success(self, mock_get: MagicMock, client: TestClient) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "symbol": "SOLUSDT",
            "priceChange": "3.50000000",
            "priceChangePercent": "2.450",
            "lastPrice": "146.25000000",
            "highPrice": "148.00000000",
            "lowPrice": "141.00000000",
            "volume": "125000.50000000",
            "quoteVolume": "18250000.00000000",
            "openTime": 1700000000000,
            "closeTime": 1700086400000,
        }
        mock_get.return_value = mock_response

        res = client.get("/api/market/ticker?symbol=SOLUSDT")
        assert res.status_code == 200
        data = res.json()

        assert data["symbol"] == "SOLUSDT"
        assert data["lastPrice"] == 146.25
        assert data["priceChange"] == 3.5
        assert data["priceChangePercent"] == 2.45
        assert data["highPrice"] == 148.0
        assert data["lowPrice"] == 141.0
        assert data["volume"] == 125000.5
        assert "raw" in data

    @patch("requests.get")
    def test_get_ticker_network_error_raises_502(
        self, mock_get: MagicMock, client: TestClient
    ) -> None:
        mock_get.side_effect = requests.exceptions.RequestException("Connection reset")

        res = client.get("/api/market/ticker?symbol=SOLUSDT")
        assert res.status_code == 502
        assert "Connection reset" in res.json()["detail"]

    @patch("requests.get")
    def test_get_ticker_invalid_response_raises_502(
        self, mock_get: MagicMock, client: TestClient
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = ["unexpected", "list"]
        mock_get.return_value = mock_response

        res = client.get("/api/market/ticker?symbol=SOLUSDT")
        assert res.status_code == 502


# ==============================================================================
# 3. PRUEBAS PARA ENDPOINTS DE PAPER TRADING
# ==============================================================================


class TestPaperTradingEndpoints:
    """Pruebas para los endpoints de gestión de Paper Trading."""

    def test_paper_status_initial_state(self, client: TestClient) -> None:
        res = client.get("/api/paper/status")
        assert res.status_code == 200
        data = res.json()

        assert data["is_running"] is False
        assert data["symbol"] == "SOLUSDT"
        assert data["interval"] == "15m"
        assert data["balance"] == 25.0
        assert data["equity"] == 25.0
        assert data["open_position"] is None
        assert data["pnl"] == 0.0
        assert data["win_rate"] == 0.0
        assert data["total_trades"] == 0

    def test_paper_start_and_stop_lifecycle(self, client: TestClient) -> None:
        manager = PaperTradingManager.get_instance()

        with patch.object(manager, "_run_worker", lambda: None):
            # 1. Iniciar Paper Trading
            start_payload = {
                "symbol": "SOLUSDT",
                "interval": "1h",
                "initial_balance": "25.00",
                "poll_interval": 5.0,
            }
            res_start = client.post("/api/paper/start", json=start_payload)
            assert res_start.status_code == 200
            start_data = res_start.json()
            assert start_data["status"] == "started"
            assert start_data["symbol"] == "SOLUSDT"
            assert start_data["interval"] == "1h"
            assert manager.is_running is True

            # 2. Intentar iniciar de nuevo (debe responder already_running)
            res_start_dup = client.post("/api/paper/start", json=start_payload)
            assert res_start_dup.status_code == 200
            assert res_start_dup.json()["status"] == "already_running"

            # 3. Verificar estado activo
            res_status = client.get("/api/paper/status")
            assert res_status.status_code == 200
            assert res_status.json()["is_running"] is True

            # 4. Detener Paper Trading
            res_stop = client.post("/api/paper/stop")
            assert res_stop.status_code == 200
            assert res_stop.json()["status"] == "stopped"
            assert manager.is_running is False

            # 5. Intentar detener cuando ya está detenido
            res_stop_dup = client.post("/api/paper/stop")
            assert res_stop_dup.status_code == 200
            assert res_stop_dup.json()["status"] == "not_running"

    def test_paper_trades_empty_initially(self, client: TestClient) -> None:
        res = client.get("/api/paper/trades")
        assert res.status_code == 200
        data = res.json()
        assert data["trades"] == []
        assert data["total_trades"] == 0

    def test_paper_status_with_active_position(self, client: TestClient) -> None:
        manager = PaperTradingManager.get_instance()
        broker = manager.broker

        # Abrir posición simulada manualmente
        broker.open_position(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=Decimal("140.00"),
            qty=Decimal("0.15"),
            stop_loss=Decimal("135.00"),
            take_profit=Decimal("150.00"),
            reason="Prueba unitaria de posición",
        )

        res = client.get("/api/paper/status")
        assert res.status_code == 200
        data = res.json()

        assert data["open_position"] is not None
        pos = data["open_position"]
        assert pos["symbol"] == "SOLUSDT"
        assert pos["qty"] == 0.15
        assert pos["stop_loss"] == 135.0
        assert pos["take_profit"] == 150.0
        assert "unrealized_pnl" in pos

    def test_paper_trades_and_status_after_completed_trade(self, client: TestClient) -> None:
        manager = PaperTradingManager.get_instance()
        broker = manager.broker

        # 1. Abrir posición
        broker.open_position(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=Decimal("140.00"),
            qty=Decimal("0.15"),
            stop_loss=Decimal("135.00"),
            take_profit=Decimal("150.00"),
        )

        # 2. Cerrar posición con Take Profit
        broker.close_position(
            symbol="SOLUSDT",
            exit_price=Decimal("150.00"),
            exit_reason="TAKE_PROFIT",
        )

        # 3. Consultar historial de trades
        res_trades = client.get("/api/paper/trades")
        assert res_trades.status_code == 200
        trades_data = res_trades.json()

        assert trades_data["total_trades"] == 1
        trade = trades_data["trades"][0]
        assert trade["symbol"] == "SOLUSDT"
        assert trade["exit_reason"] == "TAKE_PROFIT"
        assert trade["net_pnl"] > 0
        assert trade["qty"] == 0.15

        # 4. Consultar status consolidado
        res_status = client.get("/api/paper/status")
        assert res_status.status_code == 200
        status_data = res_status.json()

        assert status_data["total_trades"] == 1
        assert status_data["win_rate"] == 100.0
        assert status_data["pnl"] > 0


# ==============================================================================
# 4. PRUEBAS PARA WEBSOCKET /ws/live
# ==============================================================================


class TestWebSocketLiveEndpoint:
    """Pruebas para el streaming en vivo de WebSockets."""

    def test_websocket_connect_and_receive_initial_message(self, client: TestClient) -> None:
        with client.websocket_connect("/ws/live") as websocket:
            # 1. Primer mensaje: confirmación de conexión y estado inicial
            initial_msg = websocket.receive_json()
            assert initial_msg["type"] == "connection_established"
            assert initial_msg["symbol"] == "SOLUSDT"
            assert "status" in initial_msg
            assert initial_msg["status"]["balance"] == 25.0

            # 2. Ping-Pong test
            websocket.send_text("ping")
            received_messages = []
            for _ in range(2):
                msg = websocket.receive_json()
                received_messages.append(msg)
                if msg.get("type") == "pong":
                    break

            types = [m.get("type") for m in received_messages]
            assert "pong" in types


# ==============================================================================
# 5. PRUEBAS DE ARCHIVOS ESTÁTICOS Y VISTAS HTML
# ==============================================================================


class TestStaticAndHtmlRoutes:
    """Pruebas para servir el Dashboard Web estático."""

    def test_root_route_serves_html(self, client: TestClient) -> None:
        res = client.get("/")
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")

    def test_dashboard_route_serves_html(self, client: TestClient) -> None:
        res = client.get("/dashboard")
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")

    def test_static_files_accessible(self, client: TestClient) -> None:
        res = client.get("/static/styles.css")
        assert res.status_code == 200


# ==============================================================================
# 6. PRUEBAS PARA EL LANZADOR CLI run_dashboard.py
# ==============================================================================


class TestRunDashboardCli:
    """Pruebas para el script CLI de inicio del Dashboard."""

    def test_print_banner_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_banner(host="127.0.0.1", port=8000, reload=False)
        captured = capsys.readouterr().out
        assert "CHIMUELO PRIME — DASHBOARD SERVER" in captured
        assert "http://localhost:8000/" in captured

    @patch("uvicorn.run")
    def test_main_cli_execution(self, mock_uvicorn_run: MagicMock) -> None:
        run_dashboard_main(["--host", "127.0.0.1", "--port", "8080", "--reload"])
        mock_uvicorn_run.assert_called_once_with(
            "chimuelo_prime.orchestrator.dashboard_server:app",
            host="127.0.0.1",
            port=8080,
            reload=True,
            workers=1,
            log_level="info",
        )
