"""Tests unitarios e integrales para el servidor web de FastAPI (M8)."""

from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from chimuelo_prime.orchestrator.web_server import BotManager, app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_status_endpoint_empty_db(client: TestClient, tmp_path: Path) -> None:
    # Configurar una ruta de base de datos vacía
    db_file = tmp_path / "test_status_empty.db"
    db_url = f"sqlite:///{db_file}"

    manager = BotManager.get_instance()
    manager.db_url = db_url
    manager.config_path = Path("non_existent_config.yaml")

    res = client.get("/api/status")
    assert res.status_code == 200
    json_data = res.json()
    assert json_data["is_running"] is False
    assert json_data["symbols"] == []


@patch("chimuelo_prime.orchestrator.web_server.create_engine")
def test_status_endpoint_with_data(
    mock_create_engine: MagicMock, client: TestClient, tmp_path: Path
) -> None:
    db_file = tmp_path / "test_status.db"
    db_url = f"sqlite:///{db_file}"

    # Build DB and tables
    from chimuelo_prime.grid_state.database import build_engine

    engine = build_engine(db_url)
    mock_create_engine.return_value = engine

    # Populate DB with mock data (GridLevel, Snapshot, Order)
    from sqlalchemy.orm import Session

    from chimuelo_prime.grid_state.schema import GridLevel, Order, Snapshot

    with Session(engine) as session:
        buy_order = Order(
            order_id=123,
            symbol="SOLUSDT",
            price=Decimal("110.00"),
            qty=Decimal("1.00"),
            side="BUY",
            status="FILLED",
            created_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
            updated_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        )
        sell_order = Order(
            order_id=124,
            symbol="SOLUSDT",
            price=Decimal("120.00"),
            qty=Decimal("1.00"),
            side="SELL",
            status="NEW",
            created_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
            updated_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        )
        session.add_all([buy_order, sell_order])
        session.commit()

        level1 = GridLevel(
            level_id=1,
            symbol="SOLUSDT",
            lower_price=Decimal("100.00"),
            upper_price=Decimal("120.00"),
            buy_order_id=123,
            sell_order_id=124,
            created_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        )
        session.add(level1)

        snapshot = Snapshot(
            snapshot_id=1,
            symbol="SOLUSDT",
            equity=Decimal("5000.00"),
            cash=Decimal("2000.00"),
            inventory=Decimal("25.00"),
            created_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        )
        session.add(snapshot)
        session.commit()

    manager = BotManager.get_instance()
    manager.db_url = db_url

    # Mock de Config
    with patch(
        "chimuelo_prime.orchestrator.web_server.load_orchestrator_config"
    ) as mock_load_config:
        mock_config = MagicMock()
        mock_config.symbols = ["SOLUSDT"]
        mock_load_config.return_value = mock_config

        res = client.get("/api/status")
        assert res.status_code == 200
        json_data = res.json()
        assert json_data["is_running"] is False
        assert "SOLUSDT" in json_data["data"]
        assert json_data["data"]["SOLUSDT"]["snapshot"]["equity"] == "5000.00000000"
        assert json_data["data"]["SOLUSDT"]["levels"][0]["status"] == "ACTIVE_SELL"

    engine.dispose()


@patch("chimuelo_prime.orchestrator.web_server.Orchestrator")
@patch("chimuelo_prime.orchestrator.web_server.load_orchestrator_config")
def test_start_and_stop_endpoints(
    mock_load_config: MagicMock,
    mock_orchestrator_class: MagicMock,
    client: TestClient,
) -> None:
    mock_orchestrator = MagicMock()
    mock_orchestrator_class.return_value = mock_orchestrator

    manager = BotManager.get_instance()
    # Asegurar que el bot esté inactivo
    manager._running = False

    # Evitamos la ejecución real del hilo de fondo para prevenir bloqueos de TestClient
    with patch.object(BotManager, "_run_orchestrator", lambda self: None):
        # 1. Iniciar Bot
        res = client.post(
            "/api/start",
            json={"config_path": "config/chimuelo.yaml", "db_url": "sqlite:///:memory:"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "success"
        assert manager.is_running() is True

        # Intentar iniciar de nuevo (debe fallar)
        res = client.post(
            "/api/start",
            json={"config_path": "config/chimuelo.yaml", "db_url": "sqlite:///:memory:"},
        )
        assert res.status_code == 400

        # 2. Detener Bot
        res = client.post("/api/stop")
        assert res.status_code == 200
        assert res.json()["status"] == "success"
        assert manager.is_running() is False

        # Intentar detener de nuevo (debe fallar)
        res = client.post("/api/stop")
        assert res.status_code == 400


@patch("chimuelo_prime.orchestrator.web_server.Orchestrator")
@patch("chimuelo_prime.orchestrator.web_server.load_orchestrator_config")
@patch("chimuelo_prime.orchestrator.web_server.BinanceAuthenticatedClient")
@patch("chimuelo_prime.order_execution.executor.OrderExecutor")
@patch("chimuelo_prime.api_client.models.BinanceCredentials.from_env")
def test_panic_stop_endpoint(
    mock_from_env: MagicMock,
    mock_executor_class: MagicMock,
    mock_auth_client_class: MagicMock,
    mock_load_config: MagicMock,
    mock_orchestrator_class: MagicMock,
    client: TestClient,
) -> None:
    mock_orchestrator = MagicMock()
    mock_orchestrator_class.return_value = mock_orchestrator

    mock_executor = MagicMock()
    mock_executor_class.return_value = mock_executor

    mock_config = MagicMock()
    mock_config.symbols = ["SOLUSDT"]
    mock_load_config.return_value = mock_config

    manager = BotManager.get_instance()
    manager.orchestrator = mock_orchestrator
    manager._running = True

    # Activar Pánico
    res = client.post("/api/panic")
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert manager.is_running() is False

    # Verificar que se llamó a la cancelación de emergencia
    mock_auth_client_class.return_value.delete.assert_called_once_with(
        "/api/v3/openOrders",
        params={"symbol": "SOLUSDT"},
        weight=1,
    )


@patch("chimuelo_prime.orchestrator.web_server.HistoricalDataLoader")
def test_candles_endpoint(mock_loader_class: MagicMock, client: TestClient) -> None:
    mock_candle = MagicMock()
    mock_candle.open_time = 1779458774000
    mock_candle.timestamp = datetime.datetime.fromtimestamp(1779458774, tz=datetime.UTC).replace(
        tzinfo=None
    )
    mock_candle.open = Decimal("120.0")
    mock_candle.high = Decimal("125.0")
    mock_candle.low = Decimal("118.0")
    mock_candle.close = Decimal("122.0")
    mock_candle.volume = Decimal("1000.0")

    mock_loader = MagicMock()
    mock_loader.get_candles.return_value = [mock_candle]
    mock_loader_class.return_value = mock_loader

    res = client.get("/api/candles?symbol=SOLUSDT&interval=1h&days=1")
    assert res.status_code == 200
    json_data = res.json()
    assert json_data["symbol"] == "SOLUSDT"
    assert len(json_data["candles"]) == 1
    assert json_data["candles"][0]["open"] == 120.0
    assert json_data["candles"][0]["time"] == 1779458774


def test_ws_endpoint(client: TestClient) -> None:
    with client.websocket_connect("/api/ws") as websocket:
        # Al conectar, debería mandar los logs históricos iniciales
        # Y podemos mandar mensajes de ping si queremos
        websocket.send_text("ping")
        data = websocket.receive_json()
        # Puede ser tipo "log" o "status"
        assert "type" in data


def test_websocket_log_handler_emit() -> None:
    import logging

    from chimuelo_prime.orchestrator.web_server import log_handler

    # Emit a log message and verify it is captured in queue
    logger = logging.getLogger("test_logger")
    logger.addHandler(log_handler)
    logger.warning("Test warning log")

    # Verify it exists in log_handler's queue
    found = any("Test warning log" in msg for msg in log_handler.log_queue)
    assert found is True


@patch("chimuelo_prime.orchestrator.web_server.HistoricalDataLoader")
def test_candles_endpoint_exception(mock_loader_class: MagicMock, client: TestClient) -> None:
    mock_loader = MagicMock()
    mock_loader.get_candles.side_effect = Exception("Candle loading failure")
    mock_loader_class.return_value = mock_loader

    res = client.get("/api/candles?symbol=SOLUSDT&interval=1h&days=1")
    assert res.status_code == 500
    assert "Candle loading failure" in res.json()["detail"]


@patch("chimuelo_prime.orchestrator.web_server.create_engine")
def test_status_endpoint_db_exception(mock_create_engine: MagicMock, client: TestClient) -> None:
    mock_create_engine.side_effect = Exception("DB failure")
    res = client.get("/api/status")
    assert res.status_code == 200  # Catch and ignore db errors cleanly


@patch("chimuelo_prime.orchestrator.web_server.load_orchestrator_config")
def test_start_bot_invalid_config(mock_load_config: MagicMock, client: TestClient) -> None:
    mock_load_config.side_effect = Exception("Invalid YAML format")
    res = client.post(
        "/api/start",
        json={"config_path": "config/chimuelo.yaml", "db_url": "sqlite:///:memory:"},
    )
    assert res.status_code == 400
    assert "Invalid YAML format" in res.json()["detail"]
