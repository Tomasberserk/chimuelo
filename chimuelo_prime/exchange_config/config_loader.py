"""Cargador y validador de configuración YAML para Chimuelo Prime.

Responsabilidades (SRP):
    1. Leer el archivo `chimuelo.yaml` desde la ruta inyectada.
    2. Parsear el YAML con `PyYAML` (safe_load — nunca full_load).
    3. Validar la estructura con un modelo Pydantic interno.
    4. Retornar un objeto `ChimueloConfig` inmutable y completamente tipado.

Excepciones:
    - `ConfigFileNotFoundError`: ruta no existe.
    - `ConfigValidationError`: YAML malformado o schema inválido.

REGLA: la ruta del archivo se inyecta como `Path`, nunca hardcodeada aquí.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from chimuelo_prime.exchange_config.exceptions import (
    ConfigFileNotFoundError,
    ConfigValidationError,
)
from chimuelo_prime.exchange_config.logger import get_logger


# --------------------------------------------------------------------------- #
# Schema interno (Pydantic) — modela la estructura de chimuelo.yaml
# --------------------------------------------------------------------------- #
class EnvironmentConfig(BaseModel):
    """Configuración de un entorno específico (testnet o production)."""

    model_config = ConfigDict(frozen=True)

    base_url: str = Field(
        ..., min_length=1, description="URL base del API REST de Binance"
    )
    ws_base_url: str = Field(
        ..., min_length=1, description="URL base del WebSocket de Binance"
    )
    http_timeout_seconds: int = Field(
        ..., gt=0, le=120, description="Timeout HTTP en segundos"
    )


class LoggingConfig(BaseModel):
    """Configuración del sistema de logging."""

    model_config = ConfigDict(frozen=True)

    format: Literal["json", "console"] = Field(
        default="json",
        description="Formato de salida: 'json' (producción) o 'console' (desarrollo)",
    )
    level: Literal["debug", "info", "warning", "error", "critical"] = Field(
        default="info",
        description="Nivel mínimo de severidad de logs",
    )


class ChimueloConfig(BaseModel):
    """Configuración completa de Chimuelo Prime, cargada desde chimuelo.yaml.

    El modelo es inmutable (`frozen=True`): una vez construido, no puede
    ser mutado. Si la configuración cambia, se debe crear una nueva instancia.
    """

    model_config = ConfigDict(frozen=True)

    active_environment: Literal["testnet", "production"] = Field(
        ...,
        description="Entorno activo. Cambiar este valor alterna testnet/producción.",
    )
    environments: dict[str, EnvironmentConfig] = Field(
        ..., description="Mapa de entornos disponibles"
    )
    symbols: list[str] = Field(
        ..., min_length=1, description="Lista de símbolos habilitados para operar"
    )
    logging: LoggingConfig = Field(
        default_factory=LoggingConfig,
        description="Configuración del sistema de logging",
    )

    @model_validator(mode="after")
    def _active_env_must_exist(self) -> ChimueloConfig:
        """Valida que `active_environment` esté definido en `environments`."""
        if self.active_environment not in self.environments:
            raise ValueError(
                f"active_environment='{self.active_environment}' no está definido "
                f"en environments. Disponibles: {list(self.environments.keys())}"
            )
        return self

    @property
    def active_env(self) -> EnvironmentConfig:
        """Acceso directo al entorno activo sin indexar el dict manualmente."""
        return self.environments[self.active_environment]


# --------------------------------------------------------------------------- #
# Función pública de carga
# --------------------------------------------------------------------------- #
def load_config(config_path: Path) -> ChimueloConfig:
    """Carga y valida el archivo `chimuelo.yaml` desde `config_path`.

    Args:
        config_path: ruta absoluta o relativa al archivo YAML.
                     Debe ser inyectada por el llamador — nunca hardcodeada.

    Returns:
        `ChimueloConfig` inmutable y completamente validado.

    Raises:
        ConfigFileNotFoundError: si `config_path` no existe.
        ConfigValidationError:   si el YAML está malformado o el schema es inválido.
    """
    log = get_logger(__name__)

    if not config_path.exists():
        raise ConfigFileNotFoundError(
            f"Archivo de configuración no encontrado: {config_path.resolve()}"
        )

    raw: Any
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigValidationError(
            f"Error al parsear YAML en '{config_path}': {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise ConfigValidationError(
            f"El archivo '{config_path}' no contiene un mapping YAML válido "
            f"(se obtuvo {type(raw).__name__!r})"
        )

    try:
        config = ChimueloConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigValidationError(
            f"Schema inválido en '{config_path}':\n{exc}"
        ) from exc

    log.info(  # pragma: no cover
        "config.loaded",
        path=str(config_path.resolve()),
        environment=config.active_environment,
        symbols=config.symbols,
        log_level=config.logging.level,
        log_format=config.logging.format,
    )

    return config
