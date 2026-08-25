"""Modelos de Dominio Pydantic v2 para el Módulo 10: Macro Sentiment & News Intelligence.

Tipado estricto, inmutabilidad y precisión Decimal sin floats para métricas financieras.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SentimentCategory(str, Enum):
    """Categorías estándar del Crypto Fear & Greed Index."""

    EXTREME_FEAR = "EXTREME_FEAR"      # 0 - 24: Pánico extremo en los mercados
    FEAR = "FEAR"                      # 25 - 44: Miedo moderado
    NEUTRAL = "NEUTRAL"                # 45 - 55: Mercado balanceado
    GREED = "GREED"                    # 56 - 75: Codicia / Apetito por riesgo
    EXTREME_GREED = "EXTREME_GREED"    # 76 - 100: Euforia / Sobrecompra macro


class MacroRegime(str, Enum):
    """Régimen macroeconómico y política de operación de Chimuelo Prime."""

    RISK_ON = "RISK_ON"                # Luz verde total: Condiciones alcistas/favorables
    NEUTRAL = "NEUTRAL"                # Operación estándar cuantitativa
    RISK_OFF = "RISK_OFF"              # Precaución: Reducción de riesgo o filtro estricto
    BLACK_SWAN_VETO = "BLACK_SWAN_VETO"# Veto total: Prohibido abrir nuevas compras


class MarketSentimentReport(BaseModel):
    """Reporte consolidado de sentimiento cualitativo y macroeconómico."""

    model_config = ConfigDict(frozen=True, strict=True)

    score: Decimal = Field(
        description="Puntuación numérica del Fear & Greed Index (0 a 100)",
        ge=Decimal("0.0"),
        le=Decimal("100.0"),
    )
    category: SentimentCategory = Field(description="Clasificación cualitativa de sentimiento")
    macro_regime: MacroRegime = Field(description="Régimen macroeconómico dictaminado")
    can_open_longs: bool = Field(
        default=True,
        description="Indica si la política macro autoriza compras (True) o las veta (False)",
    )
    veto_reason: str | None = Field(
        default=None,
        description="Razón detallada en caso de que las compras estén vetadas",
    )
    source: str = Field(default="Alternative.me Fear & Greed API", description="Fuente de los datos")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp de la evaluación en formato UTC",
    )
    macro_summary: str = Field(
        default="Sentimiento de mercado neutral.",
        description="Resumen explicativo para el usuario",
    )

    @field_validator("score", mode="before")
    @classmethod
    def reject_floats(cls, v: Any) -> Any:
        """Garantiza aritmética Decimal pura en las métricas de score."""
        if isinstance(v, float):
            raise TypeError(f"Floats no permitidos en modelos financieros: {v!r}")
        if v is not None and not isinstance(v, Decimal):
            return Decimal(str(v))
        return v