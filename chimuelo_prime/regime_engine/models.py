"""Modelos de Dominio, Enums e Invariantes Matemáticas para el Regime Engine.

Define las estructuras canónicas para las 5 dimensiones de estado de mercado,
los estados desacoplados de la FSM (ARMED vs ACTIVE), y los contratos
de registro forense con pureza Decimal y validación estricta de timezone UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


def ensure_utc_aware(dt: datetime) -> datetime:
    """Valida estrictamente que el datetime posea timezone y que corresponda a UTC."""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"Timestamp naive rechazado por contrato cuantitativo: {dt}")
    return dt.astimezone(UTC)


# ==============================================================================
# ENUMS DE ESTADO DE MERCADO (5 DIMENSIONES)
# ==============================================================================


class TrendRegime(str, Enum):
    """Dimensión 1: Régimen de Tendencia basado en pendiente normalizada y ADX."""

    STRONG_BULL = "STRONG_BULL"
    BULL = "BULL"
    NEUTRAL = "NEUTRAL"
    BEAR = "BEAR"
    STRONG_BEAR = "STRONG_BEAR"


class VolatilityRegime(str, Enum):
    """Dimensión 2: Régimen de Volatilidad basado en percentiles rodantes causales."""

    EXTREME_COMPRESSION = "EXTREME_COMPRESSION"  # < 10 percentil
    COMPRESSION = "COMPRESSION"                  # 10 - 25 percentil
    NORMAL = "NORMAL"                            # 25 - 75 percentil
    EXPANSION = "EXPANSION"                      # 75 - 90 percentil
    EXTREME_EXPANSION = "EXTREME_EXPANSION"      # > 90 percentil


class StructureRegime(str, Enum):
    """Dimensión 3: Estructura de Rango vs Tendencia basada en Efficiency Ratio."""

    DIRECTIONAL = "DIRECTIONAL"      # ER >= 0.60
    TRANSITIONAL = "TRANSITIONAL"    # 0.35 <= ER < 0.60
    RANGE_BOUND = "RANGE_BOUND"      # ER < 0.35


class ParticipationRegime(str, Enum):
    """Dimensión 4: Régimen de Participación basado en percentiles de volumen y TR."""

    NORMAL_PARTICIPATION = "NORMAL_PARTICIPATION"
    PARTICIPATION_EXPANSION = "PARTICIPATION_EXPANSION"  # VolumeRank >= 70
    VOLUME_SHOCK = "VOLUME_SHOCK"                        # VolumeRank >= 90 and TRRank >= 90


class DerivativesRegime(str, Enum):
    """Dimensión 5: Capa de Derivados separando estrés de desapalancamiento confirmado."""

    EXTREME_CROWDED_LONG = "EXTREME_CROWDED_LONG"
    EXTREME_CROWDED_SHORT = "EXTREME_CROWDED_SHORT"
    DERIVATIVES_STRESS = "DERIVATIVES_STRESS"                        # Funding extreme + OI drop + Vol shock
    FORCED_DELEVERAGING_CONFIRMED = "FORCED_DELEVERAGING_CONFIRMED"  # Con confirmación de liquidaciones
    NEUTRAL = "NEUTRAL"


# ==============================================================================
# ENUMS DE LA FSM DEL ROUTER Y MOTORES ALPHA
# ==============================================================================


class RouterStrategyState(str, Enum):
    """Estados desacoplados de la Máquina de Estados Finita (FSM) del Router."""

    DISABLED = "DISABLED"  # Score de compatibilidad insuficiente (< 0.45)
    ARMED = "ARMED"        # Score >= 0.70; estrategia autorizada a vigilar gatillo
    ACTIVE = "ACTIVE"      # Posición abierta tras confirmación de gatillo técnico y riesgo
    COOLDOWN = "COOLDOWN"  # Enfriamiento forzoso por N barras tras el cierre de posición


class AlphaMotorId(str, Enum):
    """Identificadores unívocos de los 4 motores de alpha canónicos."""

    ALPHA_A = "ALPHA_A_VOLATILITY_SQUEEZE"
    ALPHA_B = "ALPHA_B_DEEP_PULLBACK"
    ALPHA_C = "ALPHA_C_LIQUIDITY_SWEEP"
    ALPHA_D = "ALPHA_D_DERIVATIVES_EXHAUSTION"


class NoTradeReasonCode(str, Enum):
    """Códigos formales de motivo de no-operación para el registro forense."""

    AMBIGUOUS_REGIME = "AMBIGUOUS_REGIME"                # RegimeConfidence < 0.15
    NO_ALPHA_COMPATIBILITY = "NO_ALPHA_COMPATIBILITY"    # max(Score_s) < 0.40
    NO_TRIGGER = "NO_TRIGGER"                            # Estrategia ARMED pero sin señal técnica
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"                  # Bloqueo por período de enfriamiento
    CORRELATION_LIMIT = "CORRELATION_LIMIT"              # Límite de exposición por cluster excedido
    HERMES_VETO = "HERMES_VETO"                          # Veto macroeconómico cualitativo activo


class RegimeTransition(str, Enum):
    """Transiciones canónicas detectadas entre regímenes de mercado."""

    STABLE_REGIME = "STABLE_REGIME"
    COMPRESSION_TO_EXPANSION = "COMPRESSION_TO_EXPANSION"
    TREND_TO_PULLBACK = "TREND_TO_PULLBACK"
    TREND_TO_CLIMAX = "TREND_TO_CLIMAX"
    CLIMAX_TO_REVERSAL = "CLIMAX_TO_REVERSAL"
    RANGE_TO_SWEEP = "RANGE_TO_SWEEP"


# ==============================================================================
# MODELOS DE DOMINIO DEL VECTOR DE ESTADO Y FORENSIC LOGGING
# ==============================================================================


class MarketStateVector(BaseModel):
    """Snapshot completo e inmutable del Vector de Estado de Mercado (S_t)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    symbol: str
    timeframe: str = "1h"

    # Clasificaciones discretas de las 5 dimensiones
    trend: TrendRegime
    volatility: VolatilityRegime
    structure: StructureRegime
    participation: ParticipationRegime
    derivatives: DerivativesRegime

    # Métricas continuas subyacentes con pureza Decimal
    slope_50: Decimal
    trend_spread: Decimal
    adx_14: Decimal
    efficiency_ratio: Decimal
    atr_percentile: Decimal
    rv_percentile: Decimal
    volume_percentile: Decimal
    tr_percentile: Decimal
    z_funding: Decimal | None = None
    delta_oi_4h: Decimal | None = None

    # Contexto macro y transición
    transition: RegimeTransition = RegimeTransition.STABLE_REGIME
    context_4h_closed_timestamp: datetime | None = None

    @field_validator("timestamp", "context_4h_closed_timestamp")
    @classmethod
    def validate_utc_timestamps(cls, v: datetime | None) -> datetime | None:
        if v is not None:
            return ensure_utc_aware(v)
        return None


class ForensicDecisionLog(BaseModel):
    """Registro forense completo tanto de decisiones positivas como de abstenciones (NO_TRADE)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    symbol: str
    decision_action: str  # "TRADE_APPROVED", "NO_TRADE"
    reason_code: NoTradeReasonCode | str
    market_state: MarketStateVector
    strategy_scores: dict[str, Decimal]
    fsm_states: dict[str, RouterStrategyState]
    regime_confidence: Decimal
    hermes_veto: bool = False
    details: str = ""

    @field_validator("timestamp")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        return ensure_utc_aware(v)


# ==============================================================================
# MODELOS DE DOMINIO DEL ROUTER (FASE 3)
# ==============================================================================


class TradeDirection(str, Enum):
    """Dirección de la operación propuesta."""

    LONG = "LONG"
    SHORT = "SHORT"


class ScoreComponentBreakdown(BaseModel):
    """Desglose granular de los componentes de score para auditoría forense."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trend_component: Decimal = Field(default=Decimal("0.0"))
    volatility_component: Decimal = Field(default=Decimal("0.0"))
    structure_component: Decimal = Field(default=Decimal("0.0"))
    participation_component: Decimal = Field(default=Decimal("0.0"))
    derivatives_component: Decimal = Field(default=Decimal("0.0"))
    transition_component: Decimal = Field(default=Decimal("0.0"))
    composite_score: Decimal = Field(default=Decimal("0.0"))


class DirectionalScore(BaseModel):
    """Puntajes de compatibilidad desacoplados por dirección operativa."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    long_score: Decimal
    short_score: Decimal
    combined_score: Decimal
    long_breakdown: ScoreComponentBreakdown
    short_breakdown: ScoreComponentBreakdown


class TradeCandidate(BaseModel):
    """Candidato de trade emitido por un Alpha Motor (no por el Router)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    strategy_id: AlphaMotorId
    symbol: str
    direction: TradeDirection
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    confidence_score: Decimal
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        return ensure_utc_aware(v)


class StrategyEvaluationLog(BaseModel):
    """Registro forense detallado del estado y score de una estrategia específica."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: AlphaMotorId
    state_before: RouterStrategyState
    state_after: RouterStrategyState
    score: DirectionalScore
    hard_gate_passed: bool
    dwell_bars_before: int
    dwell_bars_after: int
    cooldown_remaining: int
    authorized_for_trigger: bool
    rejection_reason: NoTradeReasonCode | None = None


class RouterEvaluationResult(BaseModel):
    """Snapshot determinista e inmutable de la evaluación del Router en una barra t."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    symbol: str
    market_state: MarketStateVector
    strategy_evaluations: dict[AlphaMotorId, StrategyEvaluationLog]
    armed_strategies: list[AlphaMotorId]
    active_strategies: list[AlphaMotorId]
    cooldown_strategies: list[AlphaMotorId]
    hermes_entry_veto: bool
    global_action: str
    details: str = ""

    @field_validator("timestamp")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        return ensure_utc_aware(v)
