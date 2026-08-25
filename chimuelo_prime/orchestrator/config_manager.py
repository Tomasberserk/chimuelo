"""Cargador y validador de configuración multi-activo para el Orquestador (M7).

Responsabilidades:
    1. Subclasificar ChimueloConfig (M1) para añadir el bloque de estrategias.
    2. Validar que todos los símbolos activos tengan una estrategia válida asociada.
    3. Bloquear floats explícitamente en los parámetros de la estrategia.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from chimuelo_prime.exchange_config.config_loader import ChimueloConfig
from chimuelo_prime.exchange_config.exceptions import (
    ConfigFileNotFoundError,
    ConfigValidationError,
)
from chimuelo_prime.exchange_config.logger import get_logger


class StrategyConfig(BaseModel):
    """Configuración de parámetros de trading de grid por activo."""

    model_config = ConfigDict(frozen=True, strict=False)

    upper_bound: Decimal = Field(..., gt=0, description="Límite superior del grid")
    lower_bound: Decimal = Field(..., gt=0, description="Límite inferior del grid")
    grid_levels: int = Field(..., gt=1, description="Número de niveles del grid")
    capital_per_order: Decimal = Field(..., gt=0, description="Capital por orden")
    capital_weight: Decimal = Field(
        default=Decimal("1.0"),
        gt=0,
        le=1,
        description="Peso del capital para risk parity",
    )

    @field_validator(
        "upper_bound", "lower_bound", "capital_per_order", "capital_weight", mode="before"
    )
    @classmethod
    def _reject_floats(cls, v: object) -> object:
        """Bloquea floats de forma defensiva."""
        if isinstance(v, float):
            raise TypeError(
                f"float prohibido en parámetros de estrategia (valor: {v!r}). "
                "Convierte a str o Decimal en chimuelo.yaml."
            )
        return v

    @model_validator(mode="after")
    def _validate_bounds(self) -> StrategyConfig:
        """Valida la consistencia de los rangos de la estrategia."""
        if self.lower_bound >= self.upper_bound:
            raise ValueError(
                f"lower_bound={self.lower_bound} debe ser estrictamente menor que upper_bound={self.upper_bound}"
            )
        return self


class OrchestratorConfig(ChimueloConfig):
    """Configuración completa enriquecida con estrategias multi-activo."""

    model_config = ConfigDict(frozen=True)

    strategies: dict[str, StrategyConfig] = Field(
        ..., description="Estrategias de grid operativas por activo"
    )

    @model_validator(mode="after")
    def _validate_active_symbols_have_strategies(self) -> OrchestratorConfig:
        """Asegura integridad de configuración entre símbolos activos y estrategias."""
        for symbol in self.symbols:
            if symbol not in self.strategies:
                raise ValueError(
                    f"Símbolo activo '{symbol}' listado en 'symbols' "
                    "no tiene una estrategia correspondiente definida en 'strategies'."
                )
        return self


def load_orchestrator_config(config_path: Path) -> OrchestratorConfig:
    """Carga y valida el YAML enriquecido con el esquema del orquestador.

    Raises:
        ConfigFileNotFoundError: si el archivo no existe.
        ConfigValidationError: si el YAML está mal formado o no cumple con el esquema.
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
        raise ConfigValidationError(f"Error al parsear YAML en '{config_path}': {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigValidationError(
            f"El archivo '{config_path}' no contiene un mapping YAML válido."
        )

    try:
        config = OrchestratorConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigValidationError(
            f"Schema de orquestador inválido en '{config_path}':\n{exc}"
        ) from exc

    log.info(
        "orchestrator_config.loaded",
        path=str(config_path.resolve()),
        environment=config.active_environment,
        symbols=config.symbols,
    )

    return config
