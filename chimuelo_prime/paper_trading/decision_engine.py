"""Single Decision Engine: Motor Único de Decisión para Shadow y Paper Trading."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.paper_trading.decision_models import (
    DecisionAction,
    DecisionObject,
    LifecycleEvent,
    MarketRegimeSnapshot,
    ensure_utc_aware,
)
from chimuelo_prime.paper_trading.persistence import (
    BasePersistenceBackend,
    DuplicateDecisionError,
)
from chimuelo_prime.paper_trading.risk_engine import PortfolioRiskEngine
from chimuelo_prime.paper_trading.virtual_broker import VirtualBroker
from chimuelo_prime.strategies.structural_breakout import StructuralBreakoutStrategy


class CandleNotClosedError(Exception):
    """Lanzada cuando se intenta evaluar una vela que aún no ha cerrado."""


class SingleDecisionEngine:
    """Motor canónico de decisión que unifica el flujo para Shadow Mode y Live Paper Trading."""

    def __init__(
        self,
        symbol: str,
        strategy: StructuralBreakoutStrategy,
        risk_engine: PortfolioRiskEngine,
        persistence: BasePersistenceBackend | None = None,
        virtual_broker: VirtualBroker | None = None,
        validate_closed: bool = False,
    ) -> None:
        self._symbol = symbol
        self._strategy = strategy
        self._risk_engine = risk_engine
        self._persistence = persistence
        self._broker = virtual_broker
        self._validate_closed = validate_closed
        self._log = get_logger(__name__)

    @classmethod
    def compute_data_snapshot_hash(
        cls,
        candle: HistoricalCandle,
        filters_snapshot: Any,
        past_100_vols: list[Decimal],
        strategy_version: str,
        config_hash: str,
    ) -> str:
        """Calcula el hash SHA-256 inmutable de TODOS los inputs que participan en la decisión."""
        snapshot_dict = {
            "candle": {
                "timestamp": candle.timestamp.isoformat(),
                "open": str(candle.open),
                "high": str(candle.high),
                "low": str(candle.low),
                "close": str(candle.close),
                "volume": str(candle.volume),
            },
            "filters": {
                "ema100_val": str(filters_snapshot.ema100_val),
                "breakout_20_high": filters_snapshot.breakout_20_high,
                "resistance_val": str(filters_snapshot.resistance_val),
                "close_position_ratio": str(filters_snapshot.close_position_ratio),
                "volume_sma20_val": str(filters_snapshot.volume_sma20_val),
                "btc_daily_date_prev": filters_snapshot.btc_daily_date_prev,
                "btc_daily_close_prev": str(filters_snapshot.btc_daily_close_prev),
                "btc_daily_ema50_prev": str(filters_snapshot.btc_daily_ema50_prev),
                "btc_macro_bullish": filters_snapshot.btc_macro_bullish,
                "volume_p70_threshold": str(filters_snapshot.volume_p70_threshold),
                "range_span_val": str(filters_snapshot.range_span_val),
                "atr14_val": str(filters_snapshot.atr14_val),
                "range_atr_ratio": str(filters_snapshot.range_atr_ratio),
            },
            "past_100_volumes": [str(v) for v in past_100_vols],
            "strategy_version": strategy_version,
            "config_hash": config_hash,
        }
        raw_bytes = json.dumps(snapshot_dict, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw_bytes).hexdigest()

    def evaluate_bar(
        self,
        candles: list[HistoricalCandle],
        idx: int,
        execute_paper: bool = False,
    ) -> DecisionObject:
        """Evalúa una barra horaria produciendo un DecisionObject determinista."""
        candle = candles[idx]
        ensure_utc_aware(candle.timestamp)

        # Validación estricta de vela cerrada
        if self._validate_closed:
            now_utc = datetime.now(UTC)
            candle_close_time = candle.timestamp + timedelta(hours=1)
            if candle_close_time > now_utc:
                raise CandleNotClosedError(
                    f"Vela {candle.timestamp} en {self._symbol} no ha cerrado (Cierre estimado: {candle_close_time}, Hora actual: {now_utc})"
                )

        # Idempotencia previa: consultar si la decisión ya existe en BD
        if self._persistence:
            existing = self._persistence.get_decision_by_timestamp(self._symbol, candle.timestamp)
            if existing:
                return existing

        config_hash = self._strategy.get_config_hash()

        # Evaluación de los 9 gates canónicos
        filters_snapshot, signal = self._strategy.evaluate_gates(candles, idx)

        # 100 historical volumes para snapshot hash completo
        past_100_vols = [c.volume for c in candles[idx - self._strategy.VOLUME_P70_WINDOW : idx]]

        data_snapshot_hash = self.compute_data_snapshot_hash(
            candle=candle,
            filters_snapshot=filters_snapshot,
            past_100_vols=past_100_vols,
            strategy_version=self._strategy.VERSION,
            config_hash=config_hash,
        )

        regime_snapshot = MarketRegimeSnapshot(
            btc_daily_state="BULLISH" if filters_snapshot.btc_macro_bullish else "BEARISH",
            btc_4h_momentum="BULLISH" if filters_snapshot.btc_macro_bullish else "BEARISH",
            volatility_regime="EXPANSION" if filters_snapshot.range_filter_passed else "COMPRESSION",
            volume_regime="HIGH_RELATIVE_VOL" if filters_snapshot.volume_p70_passed else "NORMAL_LOW",
        )

        open_pos_count = self._broker.get_open_positions_count() if self._broker else 0
        total_exposure_usd = self._broker.get_total_exposure() if self._broker else Decimal("0")
        current_equity = self._broker.get_equity() if self._broker else self._risk_engine.current_equity

        # Cálculo tentativo de tamaño de orden para evaluar exposición proyectada
        tentative_notional = Decimal("0")
        suggested_qty = None
        if signal:
            risk_pct = self._risk_engine.get_effective_risk_pct()
            suggested_qty = self._strategy.calculate_position_size(
                account_equity=current_equity,
                entry_price=signal.price,
                stop_loss_price=signal.stop_loss,
                risk_pct=risk_pct,
            )
            tentative_notional = signal.price * suggested_qty

        # Snapshot de riesgo con exposición proyectada
        risk_snapshot = self._risk_engine.get_snapshot(
            current_time=candle.timestamp,
            open_positions_count=open_pos_count,
            total_exposure_usd=total_exposure_usd,
            proposed_trade_notional=tentative_notional,
        )

        # Determinación de acción
        action = DecisionAction.NO_SIGNAL
        why_signal = "Gates no cumplidos"
        why_allowed = ""
        why_blocked = ""

        if signal:
            why_signal = f"Señal BUY generada por {signal.reason}"
            if risk_snapshot.risk_allowed:
                action = DecisionAction.SIGNAL_GENERATED
                why_allowed = "Aprobado por Strategy y Risk Engine"
            else:
                action = DecisionAction.BLOCKED_BY_RISK
                why_blocked = risk_snapshot.rejection_reason or "Bloqueado por Risk Engine"
        else:
            if not filters_snapshot.all_gates_passed:
                failed = []
                if not filters_snapshot.price_above_ema100: failed.append("Close<=EMA100")
                if not filters_snapshot.breakout_20_high: failed.append("NoBreakout20")
                if not filters_snapshot.close_position_passed: failed.append("ClosePos<0.65")
                if not filters_snapshot.volume_sma20_passed: failed.append("Vol<1.2xSMA20")
                if not filters_snapshot.btc_macro_bullish: failed.append("BTC_Bearish_D-1")
                if not filters_snapshot.volume_p70_passed: failed.append("Vol<P70")
                if not filters_snapshot.range_filter_passed: failed.append("Range<4xATR")
                why_signal = f"Filtros fallidos: {', '.join(failed)}"

        # Deterministic decision_id based on symbol, timestamp and config_hash
        dec_seed = f"{self._symbol}:{candle.timestamp.isoformat()}:{config_hash}".encode("utf-8")
        decision_id = f"dec_{hashlib.sha256(dec_seed).hexdigest()[:16]}"

        if action == DecisionAction.SIGNAL_GENERATED:
            lifecycle = LifecycleEvent.RISK_DECISION_ALLOWED
        elif action == DecisionAction.BLOCKED_BY_RISK:
            lifecycle = LifecycleEvent.RISK_DECISION_BLOCKED
        else:
            lifecycle = LifecycleEvent.SIGNAL_GENERATED

        decision = DecisionObject(
            decision_id=decision_id,
            timestamp=candle.timestamp,
            symbol=self._symbol,
            timeframe="1h",
            strategy_version=self._strategy.VERSION,
            config_hash=config_hash,
            candle_open=candle.open,
            candle_high=candle.high,
            candle_low=candle.low,
            candle_close=candle.close,
            candle_volume=candle.volume,
            regime=regime_snapshot,
            filters=filters_snapshot,
            risk=risk_snapshot,
            action=action,
            lifecycle_event=lifecycle,
            why_signal=why_signal,
            why_allowed=why_allowed,
            why_blocked=why_blocked,
            suggested_entry_price=signal.price if signal else None,
            suggested_stop_loss=signal.stop_loss if signal else None,
            suggested_take_profit=signal.take_profit if signal else None,
            suggested_quantity=suggested_qty,
            data_snapshot_hash=data_snapshot_hash,
        )

        # Persistencia de la decisión
        if self._persistence:
            try:
                self._persistence.save_decision(decision)
                self._persistence.save_risk_state(
                    snapshot=risk_snapshot,
                    timestamp=candle.timestamp,
                    daily_start_equity=self._risk_engine.daily_start_equity,
                    current_day=self._risk_engine.current_day,
                    cooldown_until=self._risk_engine.cooldown_until,
                )
            except DuplicateDecisionError:
                pass

        # Ejecución virtual si aplica modo Paper
        if execute_paper and action == DecisionAction.SIGNAL_GENERATED and self._broker and signal and suggested_qty:
            self._broker.execute_paper_order(
                decision_id=decision.decision_id,
                symbol=self._symbol,
                timestamp=candle.timestamp,
                signal_price=signal.price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                quantity=suggested_qty,
                risk_pct_used=self._risk_engine.get_effective_risk_pct(),
            )

        return decision
