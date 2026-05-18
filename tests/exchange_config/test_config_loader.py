"""Tests para config_loader.py.

Cubre:
    - Carga válida de chimuelo.yaml.
    - ConfigFileNotFoundError si la ruta no existe.
    - ConfigValidationError si el YAML está malformado.
    - ConfigValidationError si faltan campos requeridos.
    - ConfigValidationError si active_environment no está en environments.
    - Propiedad active_env retorna el entorno correcto.
    - Inmutabilidad del config resultante.

Estrategia:
    - Se usa `tmp_path` (fixture de pytest) para crear YAMLs temporales.
    - No se toca el archivo real `config/chimuelo.yaml` — independencia total.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from chimuelo_prime.exchange_config.config_loader import (
    ChimueloConfig,
    EnvironmentConfig,
    LoggingConfig,
    load_config,
)
from chimuelo_prime.exchange_config.exceptions import (
    ConfigFileNotFoundError,
    ConfigValidationError,
)

# --------------------------------------------------------------------------- #
# Fixture: YAML válido mínimo
# --------------------------------------------------------------------------- #
VALID_CONFIG: dict = {  # type: ignore[type-arg]
    "active_environment": "testnet",
    "environments": {
        "testnet": {
            "base_url": "https://testnet.binance.vision",
            "ws_base_url": "wss://testnet.binance.vision",
            "http_timeout_seconds": 10,
        },
        "production": {
            "base_url": "https://api.binance.com",
            "ws_base_url": "wss://stream.binance.com:9443",
            "http_timeout_seconds": 10,
        },
    },
    "symbols": ["SOLUSDT"],
    "logging": {"format": "json", "level": "info"},
}


@pytest.fixture()
def valid_yaml_path(tmp_path: Path) -> Path:
    """Escribe el YAML válido en un archivo temporal y retorna su ruta."""
    p = tmp_path / "chimuelo.yaml"
    p.write_text(yaml.dump(VALID_CONFIG), encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# Tests: carga válida
# --------------------------------------------------------------------------- #
class TestLoadConfigValid:
    def test_returns_chimuelo_config(self, valid_yaml_path: Path) -> None:
        config = load_config(valid_yaml_path)
        assert isinstance(config, ChimueloConfig)

    def test_active_environment_testnet(self, valid_yaml_path: Path) -> None:
        config = load_config(valid_yaml_path)
        assert config.active_environment == "testnet"

    def test_symbols_loaded(self, valid_yaml_path: Path) -> None:
        config = load_config(valid_yaml_path)
        assert "SOLUSDT" in config.symbols

    def test_logging_format_json(self, valid_yaml_path: Path) -> None:
        config = load_config(valid_yaml_path)
        assert config.logging.format == "json"

    def test_logging_level_info(self, valid_yaml_path: Path) -> None:
        config = load_config(valid_yaml_path)
        assert config.logging.level == "info"

    def test_active_env_property_returns_testnet(self, valid_yaml_path: Path) -> None:
        """active_env debe retornar el EnvironmentConfig del entorno activo."""
        config = load_config(valid_yaml_path)
        env = config.active_env
        assert isinstance(env, EnvironmentConfig)
        assert env.base_url == "https://testnet.binance.vision"

    def test_environments_has_both_envs(self, valid_yaml_path: Path) -> None:
        config = load_config(valid_yaml_path)
        assert "testnet" in config.environments
        assert "production" in config.environments


# --------------------------------------------------------------------------- #
# Tests: logging defaults
# --------------------------------------------------------------------------- #
class TestLoggingConfigDefaults:
    def test_default_format_is_json(self) -> None:
        lc = LoggingConfig()
        assert lc.format == "json"

    def test_default_level_is_info(self) -> None:
        lc = LoggingConfig()
        assert lc.level == "info"

    def test_console_format_accepted(self) -> None:
        lc = LoggingConfig(format="console", level="debug")
        assert lc.format == "console"


# --------------------------------------------------------------------------- #
# Tests: errores de archivo
# --------------------------------------------------------------------------- #
class TestConfigFileErrors:
    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        """Ruta inexistente debe lanzar ConfigFileNotFoundError."""
        with pytest.raises(ConfigFileNotFoundError):
            load_config(tmp_path / "no_existe.yaml")

    def test_error_message_contains_path(self, tmp_path: Path) -> None:
        missing = tmp_path / "no_existe.yaml"
        with pytest.raises(ConfigFileNotFoundError, match="no_existe.yaml"):
            load_config(missing)


# --------------------------------------------------------------------------- #
# Tests: YAML malformado
# --------------------------------------------------------------------------- #
class TestMalformedYaml:
    def test_invalid_yaml_syntax_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("key: [unclosed bracket", encoding="utf-8")
        with pytest.raises(ConfigValidationError):
            load_config(bad)

    def test_non_mapping_yaml_raises(self, tmp_path: Path) -> None:
        """Un YAML que no es dict (lista, escalar) debe fallar."""
        bad = tmp_path / "list.yaml"
        bad.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ConfigValidationError):
            load_config(bad)

    def test_empty_yaml_raises(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.yaml"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(ConfigValidationError):
            load_config(empty)


# --------------------------------------------------------------------------- #
# Tests: schema inválido
# --------------------------------------------------------------------------- #
class TestSchemaValidation:
    def test_missing_active_environment_raises(self, tmp_path: Path) -> None:
        cfg = dict(VALID_CONFIG)
        del cfg["active_environment"]
        p = tmp_path / "c.yaml"
        p.write_text(yaml.dump(cfg), encoding="utf-8")
        with pytest.raises(ConfigValidationError):
            load_config(p)

    def test_missing_symbols_raises(self, tmp_path: Path) -> None:
        cfg = dict(VALID_CONFIG)
        del cfg["symbols"]
        p = tmp_path / "c.yaml"
        p.write_text(yaml.dump(cfg), encoding="utf-8")
        with pytest.raises(ConfigValidationError):
            load_config(p)

    def test_empty_symbols_list_raises(self, tmp_path: Path) -> None:
        """symbols no puede ser lista vacía (min_length=1)."""
        cfg = {**VALID_CONFIG, "symbols": []}
        p = tmp_path / "c.yaml"
        p.write_text(yaml.dump(cfg), encoding="utf-8")
        with pytest.raises(ConfigValidationError):
            load_config(p)

    def test_active_env_not_in_environments_raises(self, tmp_path: Path) -> None:
        """active_environment debe existir en el dict environments."""
        cfg = {**VALID_CONFIG, "active_environment": "staging"}
        p = tmp_path / "c.yaml"
        p.write_text(yaml.dump(cfg), encoding="utf-8")
        with pytest.raises(ConfigValidationError):
            load_config(p)

    def test_invalid_log_format_raises(self, tmp_path: Path) -> None:
        """Formato de log no reconocido debe fallar validación."""
        cfg = {**VALID_CONFIG, "logging": {"format": "xml", "level": "info"}}
        p = tmp_path / "c.yaml"
        p.write_text(yaml.dump(cfg), encoding="utf-8")
        with pytest.raises(ConfigValidationError):
            load_config(p)

    def test_invalid_log_level_raises(self, tmp_path: Path) -> None:
        cfg = {**VALID_CONFIG, "logging": {"format": "json", "level": "verbose"}}
        p = tmp_path / "c.yaml"
        p.write_text(yaml.dump(cfg), encoding="utf-8")
        with pytest.raises(ConfigValidationError):
            load_config(p)

    def test_timeout_zero_raises(self, tmp_path: Path) -> None:
        """http_timeout_seconds=0 viola gt=0."""
        cfg = {
            **VALID_CONFIG,
            "environments": {
                "testnet": {
                    "base_url": "https://testnet.binance.vision",
                    "ws_base_url": "wss://testnet.binance.vision",
                    "http_timeout_seconds": 0,
                }
            },
        }
        p = tmp_path / "c.yaml"
        p.write_text(yaml.dump(cfg), encoding="utf-8")
        with pytest.raises(ConfigValidationError):
            load_config(p)


# --------------------------------------------------------------------------- #
# Tests: inmutabilidad del config
# --------------------------------------------------------------------------- #
class TestConfigImmutability:
    def test_cannot_mutate_active_environment(self, valid_yaml_path: Path) -> None:
        from pydantic import ValidationError

        config = load_config(valid_yaml_path)
        with pytest.raises(ValidationError):
            config.active_environment = "production"  # type: ignore[misc]

    def test_cannot_mutate_symbols(self, valid_yaml_path: Path) -> None:
        from pydantic import ValidationError

        config = load_config(valid_yaml_path)
        with pytest.raises(ValidationError):
            config.symbols = ["BTCUSDT"]  # type: ignore[misc]
