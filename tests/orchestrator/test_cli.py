"""Tests unitarios para cli.py (M7)."""

from __future__ import annotations

import datetime
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from chimuelo_prime.orchestrator.cli import (
    is_pid_alive,
    main,
    run_backtest,
    show_status,
    start_bot,
    stop_bot,
)


def test_is_pid_alive_unix() -> None:
    with patch("os.name", "posix"), patch("os.kill") as mock_kill:
        # Si os.kill(pid, 0) no lanza excepcion, esta vivo
        assert is_pid_alive(12345) is True
        mock_kill.assert_called_once_with(12345, 0)

        # Si os.kill(pid, 0) lanza OSError, esta muerto
        mock_kill.side_effect = OSError()
        assert is_pid_alive(12345) is False


def test_is_pid_alive_windows() -> None:
    with patch("os.name", "nt"), patch("subprocess.check_output") as mock_check_output:
        mock_check_output.return_value = b"python.exe                  12345 Console"
        assert is_pid_alive(12345) is True

        mock_check_output.return_value = b"No tasks are running"
        assert is_pid_alive(12345) is False


# Decorators are applied bottom-up, so params are top-down:
# @patch("is_pid_alive")     -> mock_is_pid_alive  (1st)
# @patch("load_config")      -> mock_load_config    (2nd)
# @patch("Orchestrator")     -> mock_orchestrator_class (3rd)
@patch("chimuelo_prime.orchestrator.cli.is_pid_alive")
@patch("chimuelo_prime.orchestrator.cli.load_orchestrator_config")
@patch("chimuelo_prime.orchestrator.cli.Orchestrator")
def test_start_bot_success(
    mock_orchestrator_class: MagicMock,
    mock_load_config: MagicMock,
    mock_is_pid_alive: MagicMock,
    tmp_path: Path,
) -> None:
    mock_is_pid_alive.return_value = False
    mock_orchestrator = MagicMock()
    mock_orchestrator_class.return_value = mock_orchestrator

    config_path = tmp_path / "chimuelo.yaml"
    pid_file = Path("data/chimuelo.pid")
    if pid_file.exists():
        pid_file.unlink()

    try:
        start_bot(config_path, "sqlite:///:memory:")

        # Verificar que el orquestador inicio
        mock_orchestrator.start.assert_called_once()
        # El PID file debe haber sido limpiado al salir de start_bot en el finally
        assert not pid_file.exists()
    finally:
        if pid_file.exists():
            pid_file.unlink()


# Decorators applied bottom-up, params are top-down:
# @patch("is_pid_alive")  -> mock_is_pid_alive (1st)
# @patch("os.kill")       -> mock_kill         (2nd)
@patch("chimuelo_prime.orchestrator.cli.is_pid_alive")
@patch("os.kill")
def test_stop_bot_success(mock_kill: MagicMock, mock_is_pid_alive: MagicMock) -> None:
    pid_file = Path("data/chimuelo.pid")
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text("12345")

    # Primera llamada: proceso vivo. Segunda llamada: proceso muerto (graceful)
    mock_is_pid_alive.side_effect = [True, False]

    try:
        with patch("time.sleep"):  # Evitar demoras reales
            stop_bot()

        # Verificar que se envio la señal de interrupcion
        mock_kill.assert_called_once()
        assert not pid_file.exists()
    finally:
        if pid_file.exists():
            pid_file.unlink()


@patch("chimuelo_prime.orchestrator.cli.is_pid_alive")
def test_stop_bot_not_running(mock_is_pid_alive: MagicMock) -> None:
    pid_file = Path("data/chimuelo.pid")
    if pid_file.exists():
        pid_file.unlink()

    # Si no hay pid_file, stop_bot simplemente reporta y retorna
    stop_bot()
    assert not pid_file.exists()


# Decorators applied bottom-up, params are top-down:
# @patch("load_orchestrator_config")  -> mock_load_config         (1st)
# @patch("BinancePublicClient")       -> mock_public_client_class (2nd)
# @patch("ExchangeConfigService")     -> mock_service_class       (3rd)
# @patch("HistoricalDataLoader")      -> mock_loader_class        (4th)
# @patch("BacktestSimulator")         -> mock_simulator_class     (5th)
# @patch("BacktestReporter")          -> mock_reporter_class      (6th)
@patch("chimuelo_prime.orchestrator.cli.load_orchestrator_config")
@patch("chimuelo_prime.orchestrator.cli.BinancePublicClient")
@patch("chimuelo_prime.orchestrator.cli.ExchangeConfigService")
@patch("chimuelo_prime.orchestrator.cli.HistoricalDataLoader")
@patch("chimuelo_prime.orchestrator.cli.BacktestSimulator")
@patch("chimuelo_prime.orchestrator.cli.BacktestReporter")
def test_run_backtest_success(
    mock_reporter_class: MagicMock,
    mock_simulator_class: MagicMock,
    mock_loader_class: MagicMock,
    mock_service_class: MagicMock,
    mock_public_client_class: MagicMock,
    mock_load_config: MagicMock,
    tmp_path: Path,
) -> None:
    from decimal import Decimal

    from chimuelo_prime.exchange_config.models import SymbolFilters
    from chimuelo_prime.orchestrator.config_manager import StrategyConfig

    # Real symbol filters
    real_filters = SymbolFilters(
        symbol="SOLUSDT",
        tick_size=Decimal("0.01"),
        min_price=Decimal("0.01"),
        max_price=Decimal("1000.00"),
        step_size=Decimal("0.01"),
        min_qty=Decimal("0.01"),
        max_qty=Decimal("1000.00"),
        min_notional=Decimal("5.00"),
        pct_up=Decimal("5.0"),
        pct_down=Decimal("0.2"),
    )

    # Real strategy config
    real_strategy = StrategyConfig(
        upper_bound=Decimal("140.00"),
        lower_bound=Decimal("100.00"),
        grid_levels=20,
        capital_per_order=Decimal("10.00"),
        capital_weight=Decimal("1.00"),
    )

    mock_public_client = MagicMock()
    mock_public_client_class.return_value = mock_public_client

    mock_service = MagicMock()
    mock_service.fetch_symbol_filters.return_value = real_filters
    mock_service_class.return_value = mock_service

    mock_candle = MagicMock()
    mock_candle.open = 120.0
    mock_loader = MagicMock()
    mock_loader.get_candles.return_value = [mock_candle]
    mock_loader_class.return_value = mock_loader

    mock_simulator = MagicMock()
    mock_report = MagicMock()
    mock_simulator.run.return_value = mock_report
    mock_simulator_class.return_value = mock_simulator

    mock_reporter = MagicMock()
    mock_reporter_class.return_value = mock_reporter

    # Config
    mock_config = MagicMock()
    mock_config.strategies = {"SOLUSDT": real_strategy}
    mock_config.active_env = MagicMock()
    mock_config.active_env.base_url = "https://testnet.binance.vision"
    mock_config.active_env.http_timeout_seconds = 10
    mock_load_config.return_value = mock_config

    run_backtest(
        config_path=Path("config/chimuelo.yaml"),
        symbol="SOLUSDT",
        days=15,
        interval="1h",
        strict=True,
    )

    mock_simulator_class.assert_called_once()
    mock_simulator.run.assert_called_once_with(recreate_buy_on_sell_fill=False)
    mock_reporter_class.assert_called_once_with(mock_report)
    mock_reporter.print_terminal_report.assert_called_once()
    mock_reporter.export_json.assert_called_once()


@patch("chimuelo_prime.orchestrator.cli.start_bot")
def test_main_routing_start(mock_start_bot: MagicMock) -> None:
    test_args = [
        "cli.py",
        "--config",
        "config/chimuelo.yaml",
        "--db",
        "sqlite:///chimuelo.db",
        "start",
    ]
    with patch.object(sys, "argv", test_args):
        main()
    mock_start_bot.assert_called_once_with(Path("config/chimuelo.yaml"), "sqlite:///chimuelo.db")


@patch("chimuelo_prime.orchestrator.cli.stop_bot")
def test_main_routing_stop(mock_stop_bot: MagicMock) -> None:
    test_args = ["cli.py", "stop"]
    with patch.object(sys, "argv", test_args):
        main()
    mock_stop_bot.assert_called_once()


@patch("chimuelo_prime.orchestrator.cli.show_status")
def test_main_routing_status(mock_show_status: MagicMock) -> None:
    test_args = [
        "cli.py",
        "--config",
        "config/chimuelo.yaml",
        "--db",
        "sqlite:///chimuelo.db",
        "status",
    ]
    with patch.object(sys, "argv", test_args):
        main()
    mock_show_status.assert_called_once_with("sqlite:///chimuelo.db", Path("config/chimuelo.yaml"))


@patch("chimuelo_prime.orchestrator.cli.run_backtest")
def test_main_routing_backtest(mock_run_backtest: MagicMock) -> None:
    test_args = [
        "cli.py",
        "backtest",
        "--symbol",
        "SOLUSDT",
        "--days",
        "10",
        "--interval",
        "4h",
        "--strict",
    ]
    with patch.object(sys, "argv", test_args):
        main()
    mock_run_backtest.assert_called_once_with(
        Path("config/chimuelo.yaml"), "SOLUSDT", 10, "4h", True
    )


@patch("chimuelo_prime.orchestrator.cli.load_orchestrator_config")
def test_show_status_success(mock_load_config: MagicMock, tmp_path: Path) -> None:
    db_file = tmp_path / "test_status.db"
    db_url = f"sqlite:///{db_file}"

    # Build DB and tables
    from chimuelo_prime.grid_state.database import build_engine

    engine = build_engine(db_url)

    # Populate DB with mock data (GridLevel, Snapshot, Order)
    import datetime
    from decimal import Decimal

    from sqlalchemy.orm import Session

    from chimuelo_prime.grid_state.schema import GridLevel, Order, Snapshot

    with Session(engine) as session:
        # Create mock Buy & Sell Orders
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

        # Create mock GridLevel
        level1 = GridLevel(
            level_id=1,
            symbol="SOLUSDT",
            lower_price=Decimal("100.00"),
            upper_price=Decimal("120.00"),
            buy_order_id=123,
            sell_order_id=124,
            created_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        )
        level2 = GridLevel(
            level_id=2,
            symbol="SOLUSDT",
            lower_price=Decimal("120.00"),
            upper_price=Decimal("140.00"),
            buy_order_id=None,
            sell_order_id=None,
            created_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        )
        session.add_all([level1, level2])

        # Create mock Snapshot
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

    engine.dispose()

    # Mock Config
    mock_config = MagicMock()
    mock_config.symbols = ["SOLUSDT"]
    mock_load_config.return_value = mock_config

    # Call show_status
    show_status(db_url, Path("config/chimuelo.yaml"))


@patch("chimuelo_prime.orchestrator.cli.load_orchestrator_config")
def test_show_status_empty_db(mock_load_config: MagicMock, tmp_path: Path) -> None:
    db_file = tmp_path / "test_status_empty.db"
    db_url = f"sqlite:///{db_file}"

    from chimuelo_prime.grid_state.database import build_engine

    engine = build_engine(db_url)
    engine.dispose()

    mock_config = MagicMock()
    mock_config.symbols = ["SOLUSDT"]
    mock_load_config.return_value = mock_config

    show_status(db_url, Path("config/chimuelo.yaml"))


def test_show_status_no_db() -> None:
    show_status("sqlite:///non_existent_db_file.db", Path("config/chimuelo.yaml"))


@patch("chimuelo_prime.orchestrator.cli.load_orchestrator_config")
def test_show_status_config_load_failure(mock_load_config: MagicMock, tmp_path: Path) -> None:
    mock_load_config.side_effect = Exception("Config load failed")

    db_file = tmp_path / "test_status_cfg.db"
    db_url = f"sqlite:///{db_file}"

    from chimuelo_prime.grid_state.database import build_engine

    engine = build_engine(db_url)

    # Populate a distinct level so it can query symbols from DB
    from decimal import Decimal

    from sqlalchemy.orm import Session

    from chimuelo_prime.grid_state.schema import GridLevel

    with Session(engine) as session:
        level = GridLevel(
            level_id=1,
            symbol="SOLUSDT",
            lower_price=Decimal("100.00"),
            upper_price=Decimal("120.00"),
            created_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        )
        session.add(level)
        session.commit()
    engine.dispose()

    show_status(db_url, Path("config/chimuelo.yaml"))


@patch("chimuelo_prime.orchestrator.cli.is_pid_alive")
def test_start_bot_already_running(mock_is_pid_alive: MagicMock, tmp_path: Path) -> None:
    mock_is_pid_alive.return_value = True
    pid_file = Path("data/chimuelo.pid")
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text("99999")

    try:
        with pytest.raises(SystemExit) as excinfo:
            start_bot(tmp_path / "config.yaml", "sqlite:///:memory:")
        assert excinfo.value.code == 1
    finally:
        if pid_file.exists():
            pid_file.unlink()


@patch("chimuelo_prime.orchestrator.cli.is_pid_alive")
@patch("chimuelo_prime.orchestrator.cli.load_orchestrator_config")
@patch("chimuelo_prime.orchestrator.cli.Orchestrator")
def test_start_bot_exception(
    mock_orchestrator_class: MagicMock,
    mock_load_config: MagicMock,
    mock_is_pid_alive: MagicMock,
    tmp_path: Path,
) -> None:
    mock_is_pid_alive.return_value = False
    mock_orchestrator = MagicMock()
    mock_orchestrator.start.side_effect = Exception("Start failure")
    mock_orchestrator_class.return_value = mock_orchestrator

    config_path = tmp_path / "chimuelo.yaml"
    pid_file = Path("data/chimuelo.pid")
    if pid_file.exists():
        pid_file.unlink()

    try:
        with pytest.raises(SystemExit) as excinfo:
            start_bot(config_path, "sqlite:///:memory:")
        assert excinfo.value.code == 1
        assert not pid_file.exists()
    finally:
        if pid_file.exists():
            pid_file.unlink()


def test_stop_bot_corrupt_pid() -> None:
    pid_file = Path("data/chimuelo.pid")
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text("not-an-integer")

    try:
        stop_bot()
        assert not pid_file.exists()
    finally:
        if pid_file.exists():
            pid_file.unlink()


@patch("chimuelo_prime.orchestrator.cli.is_pid_alive")
def test_stop_bot_pid_not_alive(mock_is_pid_alive: MagicMock) -> None:
    mock_is_pid_alive.return_value = False
    pid_file = Path("data/chimuelo.pid")
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text("99999")

    try:
        stop_bot()
        assert not pid_file.exists()
    finally:
        if pid_file.exists():
            pid_file.unlink()


@patch("chimuelo_prime.orchestrator.cli.is_pid_alive")
@patch("os.kill")
def test_stop_bot_timeout(mock_kill: MagicMock, mock_is_pid_alive: MagicMock) -> None:
    pid_file = Path("data/chimuelo.pid")
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text("99999")

    # Process remains alive throughout all checks
    mock_is_pid_alive.return_value = True

    try:
        with patch("time.sleep"):
            stop_bot()
        mock_kill.assert_called_once()
        assert pid_file.exists()  # Did not delete PID file since it didn't stop
    finally:
        if pid_file.exists():
            pid_file.unlink()


@patch("chimuelo_prime.orchestrator.cli.is_pid_alive")
@patch("os.kill")
def test_stop_bot_kill_exception(mock_kill: MagicMock, mock_is_pid_alive: MagicMock) -> None:
    pid_file = Path("data/chimuelo.pid")
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text("99999")

    mock_is_pid_alive.return_value = True
    mock_kill.side_effect = Exception("Permission denied")

    try:
        stop_bot()
        mock_kill.assert_called_once()
        assert pid_file.exists()
    finally:
        if pid_file.exists():
            pid_file.unlink()


@patch("chimuelo_prime.orchestrator.cli.load_orchestrator_config")
@patch("chimuelo_prime.orchestrator.cli.BinancePublicClient")
@patch("chimuelo_prime.orchestrator.cli.ExchangeConfigService")
@patch("chimuelo_prime.orchestrator.cli.HistoricalDataLoader")
def test_run_backtest_empty_candles(
    mock_loader_class: MagicMock,
    mock_service_class: MagicMock,
    mock_public_client_class: MagicMock,
    mock_load_config: MagicMock,
) -> None:
    from decimal import Decimal

    from chimuelo_prime.exchange_config.models import SymbolFilters

    real_filters = SymbolFilters(
        symbol="SOLUSDT",
        tick_size=Decimal("0.01"),
        min_price=Decimal("0.01"),
        max_price=Decimal("1000.00"),
        step_size=Decimal("0.01"),
        min_qty=Decimal("0.01"),
        max_qty=Decimal("1000.00"),
        min_notional=Decimal("5.00"),
        pct_up=Decimal("5.0"),
        pct_down=Decimal("0.2"),
    )

    mock_public_client = MagicMock()
    mock_public_client_class.return_value = mock_public_client

    mock_service = MagicMock()
    mock_service.fetch_symbol_filters.return_value = real_filters
    mock_service_class.return_value = mock_service

    mock_loader = MagicMock()
    mock_loader.get_candles.return_value = []  # Empty
    mock_loader_class.return_value = mock_loader

    mock_config = MagicMock()
    mock_config.strategies = {}
    mock_load_config.return_value = mock_config

    run_backtest(
        config_path=Path("config/chimuelo.yaml"),
        symbol="SOLUSDT",
        days=15,
        interval="1h",
        strict=True,
    )
    mock_loader.get_candles.assert_called_once()


@patch("chimuelo_prime.orchestrator.cli.load_orchestrator_config")
@patch("chimuelo_prime.orchestrator.cli.BinancePublicClient")
@patch("chimuelo_prime.orchestrator.cli.ExchangeConfigService")
@patch("chimuelo_prime.orchestrator.cli.HistoricalDataLoader")
@patch("chimuelo_prime.orchestrator.cli.BacktestSimulator")
@patch("chimuelo_prime.orchestrator.cli.BacktestReporter")
def test_run_backtest_no_strategy_fallback(
    mock_reporter_class: MagicMock,
    mock_simulator_class: MagicMock,
    mock_loader_class: MagicMock,
    mock_service_class: MagicMock,
    mock_public_client_class: MagicMock,
    mock_load_config: MagicMock,
) -> None:
    from decimal import Decimal

    from chimuelo_prime.exchange_config.models import SymbolFilters

    real_filters = SymbolFilters(
        symbol="SOLUSDT",
        tick_size=Decimal("0.01"),
        min_price=Decimal("0.01"),
        max_price=Decimal("1000.00"),
        step_size=Decimal("0.01"),
        min_qty=Decimal("0.01"),
        max_qty=Decimal("1000.00"),
        min_notional=Decimal("5.00"),
        pct_up=Decimal("5.0"),
        pct_down=Decimal("0.2"),
    )

    mock_public_client = MagicMock()
    mock_public_client_class.return_value = mock_public_client

    mock_service = MagicMock()
    mock_service.fetch_symbol_filters.return_value = real_filters
    mock_service_class.return_value = mock_service

    mock_candle = MagicMock()
    mock_candle.open = Decimal("120.0")
    mock_loader = MagicMock()
    mock_loader.get_candles.return_value = [mock_candle]
    mock_loader_class.return_value = mock_loader

    mock_simulator = MagicMock()
    mock_report = MagicMock()
    mock_simulator.run.return_value = mock_report
    mock_simulator_class.return_value = mock_simulator

    mock_reporter = MagicMock()
    mock_reporter_class.return_value = mock_reporter

    # Config has no strategies for SOLUSDT
    mock_config = MagicMock()
    mock_config.strategies = {}
    mock_config.active_env = MagicMock()
    mock_config.active_env.base_url = "https://testnet.binance.vision"
    mock_config.active_env.http_timeout_seconds = 10
    mock_load_config.return_value = mock_config

    run_backtest(
        config_path=Path("config/chimuelo.yaml"),
        symbol="SOLUSDT",
        days=15,
        interval="1h",
        strict=False,  # continuous mode
    )

    mock_simulator_class.assert_called_once()
    mock_simulator.run.assert_called_once_with(recreate_buy_on_sell_fill=True)


@patch("chimuelo_prime.orchestrator.cli.load_orchestrator_config")
def test_run_backtest_exception(mock_load_config: MagicMock) -> None:
    mock_load_config.side_effect = Exception("Backtest critical error")

    # Should catch exception and not raise it
    run_backtest(
        config_path=Path("config/chimuelo.yaml"),
        symbol="SOLUSDT",
        days=15,
        interval="1h",
        strict=True,
    )


@patch("uvicorn.run")
def test_run_gui_success(mock_uvicorn_run: MagicMock) -> None:
    from chimuelo_prime.orchestrator.cli import run_gui

    run_gui("127.0.0.1", 8000, Path("config/chimuelo.yaml"), "sqlite:///test.db")
    mock_uvicorn_run.assert_called_once()


@patch("uvicorn.run")
def test_run_gui_exception(mock_uvicorn_run: MagicMock) -> None:
    from chimuelo_prime.orchestrator.cli import run_gui

    mock_uvicorn_run.side_effect = Exception("Uvicorn crash")
    # should catch exception and not raise it
    run_gui("127.0.0.1", 8000, Path("config/chimuelo.yaml"), "sqlite:///test.db")


@patch("chimuelo_prime.orchestrator.cli.run_gui")
def test_main_routing_gui(mock_run_gui: MagicMock) -> None:
    test_args = ["cli.py", "gui", "--host", "127.0.0.1", "--port", "8000"]
    with patch.object(sys, "argv", test_args):
        main()
    mock_run_gui.assert_called_once_with(
        "127.0.0.1", 8000, Path("config/chimuelo.yaml"), "sqlite:///chimuelo.db"
    )
