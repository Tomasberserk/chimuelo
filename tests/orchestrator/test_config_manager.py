"""Tests unitarios para config_manager.py (M7)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from chimuelo_prime.exchange_config.exceptions import ConfigValidationError
from chimuelo_prime.orchestrator.config_manager import (
    OrchestratorConfig,
    StrategyConfig,
    load_orchestrator_config,
)


@pytest.fixture
def valid_yaml_content() -> str:
    return """
active_environment: "testnet"
environments:
  testnet:
    base_url: "https://testnet.binance.vision"
    ws_base_url: "wss://testnet.binance.vision"
    http_timeout_seconds: 10
symbols:
  - "SOLUSDT"
strategies:
  SOLUSDT:
    upper_bound: "140.00"
    lower_bound: "100.00"
    grid_levels: 20
    capital_per_order: "10.00"
    capital_weight: "1.00"
"""


def test_strategy_config_valid() -> None:
    config = StrategyConfig(
        upper_bound=Decimal("140.0"),
        lower_bound=Decimal("100.0"),
        grid_levels=20,
        capital_per_order=Decimal("10.0"),
        capital_weight=Decimal("1.0"),
    )
    assert config.upper_bound == Decimal("140.0")
    assert config.lower_bound == Decimal("100.0")
    assert config.grid_levels == 20


def test_strategy_config_rejects_floats() -> None:
    # Intenta instanciar usando floats (debe lanzar TypeError o ValidationError por tipo estricto)
    with pytest.raises((TypeError, ValidationError)):
        StrategyConfig(
            upper_bound=140.0,  # float
            lower_bound=Decimal("100.0"),
            grid_levels=20,
            capital_per_order=Decimal("10.0"),
            capital_weight=Decimal("1.0"),
        )


def test_strategy_config_invalid_bounds() -> None:
    with pytest.raises(ValidationError, match="lower_bound=150.* debe ser estrictamente menor"):
        StrategyConfig(
            upper_bound=Decimal("100.0"),
            lower_bound=Decimal("150.0"),
            grid_levels=20,
            capital_per_order=Decimal("10.0"),
            capital_weight=Decimal("1.0"),
        )


def test_orchestrator_config_missing_strategy() -> None:
    # Símbolo "SOLUSDT" activo pero sin estrategia definida para él
    raw = {
        "active_environment": "testnet",
        "environments": {
            "testnet": {
                "base_url": "https://testnet.binance.vision",
                "ws_base_url": "wss://testnet.binance.vision",
                "http_timeout_seconds": 10,
            }
        },
        "symbols": ["SOLUSDT", "BTCUSDT"],
        "strategies": {
            "SOLUSDT": {
                "upper_bound": Decimal("140.00"),
                "lower_bound": Decimal("100.00"),
                "grid_levels": 20,
                "capital_per_order": Decimal("10.00"),
                "capital_weight": Decimal("1.00"),
            }
        },
    }
    with pytest.raises(ValidationError, match="activo 'BTCUSDT' listado en 'symbols'"):
        OrchestratorConfig.model_validate(raw)


def test_load_orchestrator_config_success(tmp_path: Path, valid_yaml_content: str) -> None:
    config_file = tmp_path / "chimuelo_test.yaml"
    config_file.write_text(valid_yaml_content, encoding="utf-8")

    config = load_orchestrator_config(config_file)
    assert config.active_environment == "testnet"
    assert "SOLUSDT" in config.strategies
    assert config.strategies["SOLUSDT"].upper_bound == Decimal("140.0")


def test_load_orchestrator_config_file_not_found() -> None:
    from chimuelo_prime.exchange_config.exceptions import ConfigFileNotFoundError

    with pytest.raises(ConfigFileNotFoundError):
        load_orchestrator_config(Path("non_existent_file.yaml"))


def test_load_orchestrator_config_invalid_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "corrupt.yaml"
    config_file.write_text("{invalid: yaml: content}", encoding="utf-8")

    with pytest.raises(ConfigValidationError):
        load_orchestrator_config(config_file)


def test_load_orchestrator_config_not_a_mapping(tmp_path: Path) -> None:
    config_file = tmp_path / "list.yaml"
    config_file.write_text("- item1\n- item2", encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="no contiene un mapping YAML válido"):
        load_orchestrator_config(config_file)


def test_load_orchestrator_config_invalid_schema(tmp_path: Path) -> None:
    config_file = tmp_path / "invalid_schema.yaml"
    config_file.write_text("invalid_field: 123", encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="Schema de orquestador inválido"):
        load_orchestrator_config(config_file)
