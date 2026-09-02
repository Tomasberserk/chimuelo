"""Contratos de datos inmutables y modelos de ciclo de vida para el Single Decision Engine."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


def ensure_utc_aware(dt: datetime) -> datetime:
    """Garantiza que un datetime sea timezone-aware en UTC y rechaza datetime naive."""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"Timestamp naive no permitido: {dt}. Todos los timestamps deben ser timezone-aware UTC.")
    return dt.astimezone(UTC)


class LifecycleEvent(str, Enum):
    """Ciclos de vida explícitamente separados."""
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    RISK_DECISION_ALLOWED = "RISK_DECISION_ALLOWED"
    RISK_DECISION_BLOCKED = "RISK_DECISION_BLOCKED"
    PAPER_ORDER_CREATED = "PAPER_ORDER_CREATED"
    PAPER_FILL_EXECUTED = "PAPER_FILL_EXECUTED"
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_CLOSED = "POSITION_CLOSED"


class DecisionAction(str, Enum):
    NO_SIGNAL = "NO_SIGNAL"
    BLOCKED_BY_STRATEGY = "BLOCKED_BY_STRATEGY"
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    BLOCKED_BY_RISK = "BLOCKED_BY_RISK"
    EXECUTED_PAPER_LONG = "EXECUTED_PAPER_LONG"


class RiskStateEnum(str, Enum):
    NORMAL = "NORMAL"
    REDUCED_SIZING = "REDUCED_SIZING"
    CIRCUIT_BREAKER_DAILY = "CIRCUIT_BREAKER_DAILY"
    CIRCUIT_BREAKER_MAX_DD = "CIRCUIT_BREAKER_MAX_DD"
    COOLDOWN = "COOLDOWN"


class FilterEvaluationSnapshot(BaseModel):
    """Snapshot completo y auditable de cada uno de los gates evaluados."""
    model_config = ConfigDict(frozen=True)

    # Gate 1: Trend base (Close > EMA100)
    price_above_ema100: bool
    ema100_val: Decimal
    # Gate 2: Breakout 20-bar resistance
    breakout_20_high: bool
    resistance_val: Decimal
    # Gate 3: Close in upper 35% of candle range (ratio >= 0.65)
    close_position_ratio: Decimal
    close_position_passed: bool
    # Gate 4: Volume expansion immediate (Volume >= 1.20x SMA20)
    volume_sma20_val: Decimal
    volume_sma20_passed: bool
    # Gate 5: BTC Daily macro regime (BTC Close[D-1] > BTC EMA50[D-1])
    btc_daily_date_prev: str
    btc_daily_close_prev: Decimal
    btc_daily_ema50_prev: Decimal
    btc_macro_bullish: bool
    # Gate 6: Extreme Relative Volume (Volume >= P70 of last 100 bars)
    volume_p70_threshold: Decimal
    volume_p70_passed: bool
    # Gate 7: Range maturity (Range 20 bars >= 4.0x ATR14)
    range_span_val: Decimal
    atr14_val: Decimal
    range_atr_ratio: Decimal
    range_filter_passed: bool
    # All strategy gates satisfied
    all_gates_passed: bool


class MarketRegimeSnapshot(BaseModel):
    """Contexto de régimen observable antes de la entrada."""
    model_config = ConfigDict(frozen=True)

    btc_daily_state: str = Field(description="BULLISH si BTC[D-1] > EMA50[D-1], sino BEARISH")
    btc_4h_momentum: str = Field(description="BULLISH si EMA20 > EMA50 en 4h, sino BEARISH")
    volatility_regime: str = Field(description="EXPANSION si ATR > SMA20(ATR), sino COMPRESSION")
    volume_regime: str = Field(description="HIGH_RELATIVE_VOL si Vol >= P70, sino NORMAL_LOW")


class RiskStateSnapshot(BaseModel):
    """Snapshot del estado de riesgo y capital en el momento exacto de la decisión."""
    model_config = ConfigDict(frozen=True)

    current_state: RiskStateEnum
    high_water_mark: Decimal
    current_equity: Decimal
    daily_drawdown_pct: Decimal
    peak_to_trough_drawdown_pct: Decimal
    consecutive_losses_count: int
    open_positions_count: int
    total_exposure_pct: Decimal
    risk_allowed: bool
    rejection_reason: str | None = None


class DecisionObject(BaseModel):
    """Contrato inmutable de decisión único consumido por Shadow y Paper."""
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(description="Identificador único determinista o UUID v4")
    timestamp: datetime = Field(description="Timestamp UTC de cierre de vela evaluada")
    symbol: str = Field(description="BTCUSDT o SOLUSDT")
    timeframe: str = Field(default="1h")
    strategy_version: str = Field(default="v1.0.0-frozen")
    config_hash: str = Field(description="SHA-256 de las reglas y parámetros congelados de Strategy C")

    candle_open: Decimal
    candle_high: Decimal
    candle_low: Decimal
    candle_close: Decimal
    candle_volume: Decimal

    regime: MarketRegimeSnapshot
    filters: FilterEvaluationSnapshot
    risk: RiskStateSnapshot

    action: DecisionAction
    lifecycle_event: LifecycleEvent
    why_signal: str
    why_allowed: str
    why_blocked: str

    suggested_entry_price: Decimal | None = None
    suggested_stop_loss: Decimal | None = None
    suggested_take_profit: Decimal | None = None
    suggested_quantity: Decimal | None = None
    data_snapshot_hash: str = Field(description="SHA-256 de los inputs brutos de entrada")

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp_utc(cls, v: datetime) -> datetime:
        return ensure_utc_aware(v)


class PaperOrder(BaseModel):
    """Orden virtual generada tras aprobación de riesgo."""
    model_config = ConfigDict(frozen=True)

    order_id: str
    decision_id: str
    symbol: str
    order_type: str = "MARKET_SIMULATED"
    side: str = "BUY"
    timestamp: datetime
    requested_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    quantity: Decimal
    risk_pct_used: Decimal

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp_utc(cls, v: datetime) -> datetime:
        return ensure_utc_aware(v)


class PaperFill(BaseModel):
    """Ejecución virtual simulada con slippage y comisión calculados."""
    model_config = ConfigDict(frozen=True)

    fill_id: str
    order_id: str
    decision_id: str
    symbol: str
    timestamp: datetime
    signal_price: Decimal
    fill_price: Decimal
    slippage_pct: Decimal
    quantity: Decimal
    fee_usd: Decimal
    fee_rate: Decimal = Decimal("0.0010")

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp_utc(cls, v: datetime) -> datetime:
        return ensure_utc_aware(v)


class PaperPosition(BaseModel):
    """Posición abierta o cerrada en el Paper Broker."""
    model_config = ConfigDict(frozen=True)

    position_id: str
    symbol: str
    status: str = Field(description="OPEN / CLOSED")
    entry_time: datetime
    entry_signal_price: Decimal
    fill_price: Decimal
    slippage_pct: Decimal
    quantity: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    fee_entry: Decimal

    exit_time: datetime | None = None
    exit_price: Decimal | None = None
    exit_reason: str | None = None  # TAKE_PROFIT, STOP_LOSS, CIRCUIT_BREAKER
    fee_exit: Decimal | None = None
    gross_pnl: Decimal | None = None
    net_pnl: Decimal | None = None
    r_multiple: Decimal | None = None
    duration_hours: int | None = None

    @field_validator("entry_time")
    @classmethod
    def validate_entry_time_utc(cls, v: datetime) -> datetime:
        return ensure_utc_aware(v)

    @field_validator("exit_time")
    @classmethod
    def validate_exit_time_utc(cls, v: datetime | None) -> datetime | None:
        return ensure_utc_aware(v) if v is not None else None
