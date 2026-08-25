"""Modelos de dominio para señales y estrategias cuantitativas.

Garantiza inmutabilidad y precisión Decimal estricta en todas las operaciones.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SignalType(str, Enum):
    """Tipo de señal generada por una estrategia."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class TradeSignal(BaseModel):
    """Señal de trading cuantitativa inmutable."""

    model_config = ConfigDict(frozen=True, strict=True)

    timestamp: datetime = Field(description="Fecha y hora de generación de la señal")
    symbol: str = Field(description="Símbolo del par (ej. SOLUSDT)")
    signal_type: SignalType = Field(description="Tipo de señal (BUY, SELL, HOLD)")
    price: Decimal = Field(description="Precio de referencia al momento de la señal")
    stop_loss: Decimal | None = Field(default=None, description="Precio de Stop Loss sugerido")
    take_profit: Decimal | None = Field(default=None, description="Precio de Take Profit sugerido")
    suggested_qty: Decimal | None = Field(default=None, description="Cantidad sugerida a operar")
    reason: str = Field(default="", description="Explicación cuantitativa del gatillo")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Métricas de soporte de la señal"
    )

    @field_validator("price", "stop_loss", "take_profit", "suggested_qty", mode="before")
    @classmethod
    def reject_floats(cls, v: Any) -> Any:
        if isinstance(v, float):
            raise TypeError(f"Floats no permitidos en modelos financieros: {v!r}")
        if v is not None and not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class Position(BaseModel):
    """Representación inmutable de una posición activa en el mercado."""

    model_config = ConfigDict(frozen=True, strict=True)

    symbol: str = Field(description="Símbolo del par operado")
    entry_price: Decimal = Field(description="Precio promedio de entrada")
    qty: Decimal = Field(description="Cantidad de activo base en posición")
    stop_loss: Decimal = Field(description="Nivel actual de Stop Loss")
    take_profit: Decimal = Field(description="Nivel actual de Take Profit")
    entry_time: datetime = Field(description="Momento de apertura de la posición")
    initial_risk_usd: Decimal = Field(description="Riesgo inicial en quote currency")

    @field_validator(
        "entry_price", "qty", "stop_loss", "take_profit", "initial_risk_usd", mode="before"
    )
    @classmethod
    def reject_floats(cls, v: Any) -> Any:
        if isinstance(v, float):
            raise TypeError(f"Floats no permitidos en modelos financieros: {v!r}")
        if v is not None and not isinstance(v, Decimal):
            return Decimal(str(v))
        return v
