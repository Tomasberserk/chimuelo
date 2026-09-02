"""Single Decision Engine canónico para Shadow Mode y Live Paper Trading."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.paper_trading.decision_models import (
    DecisionAction,
    DecisionObject,
    LifecycleEvent,
    MarketRegimeSnapshot,
    PaperFill,
    PaperOrder,
    PaperPosition,
    ensure_utc_aware,
)
from chimuelo_prime.paper_trading.persistence import (
    BasePersistenceBackend,
    DuplicateDecisionError,
)
from chimuelo_prime.paper_trading.risk_engine import PortfolioRiskEngine
from chimuelo_prime.paper_trading.virtual_broker import VirtualBroker
from chimuelo_prime.strategies.indicators import calculate_atr, calculate_ema
from chimuelo_prime.strategies.structural_breakout import StructuralBreakoutStrategy


class SingleDecisionEngine:
    """Motor de decisión único consumido por Shadow Mode y Paper Trading.

    Garantiza paridad estricta y determinismo absoluto: Live(t) == Replay(t).
    """

    def __init__(
        self,
        strategy: StructuralBreakoutStrategy,
        risk_engine: PortfolioRiskEngine,
        persistence: BasePersistenceBackend,
        broker: VirtualBroker | None = None,
    ) -> None:
        self._strategy = strategy
        self._risk_engine = risk_engine
        self._persistence = persistence
        self._broker = broker

    def _compute_data_snapshot_hash(
        self,
        candle: HistoricalCandle,
        btc_daily_candle: HistoricalCandle | None,
        recent_volumes: list[Decimal],
    ) -> str:
        """Calcula el hash SHA-256 de los datos de entrada exactos para auditoría."""
        payload = {
            "symbol": self._strategy._symbol,
            "timestamp": candle.timestamp.isoformat(),
            "open": str(candle.open),
            "high": str(candle.high),
            "low": str(candle.low),
            "close": str(candle.close),
            "volume": str(candle.volume),
            "btc_daily_prev_close": str(btc_daily_candle.close) if btc_daily_candle else "None",
            "recent_volumes_sample": [str(v) for v in recent_volumes[-5:]],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def evaluate_bar(
        self,
        candles_1h: list[HistoricalCandle],
        idx: int,
        btc_daily_candles: list[HistoricalCandle],
        btc_4h_candles: list[HistoricalCandle] | None = None,
        execute_paper: bool = True,
    ) -> tuple[DecisionObject, PaperPosition | None]:
        """Evalúa la barra `idx` y produce el `DecisionObject` canónico inmutable."""
        candle = candles_1h[idx]
        utc_ts = ensure_utc_aware(candle.timestamp)

        # 1. Chequeo de Idempotencia: Verificar si ya existe decisión registrada
        existing = self._persistence.get_decision_by_timestamp(self._strategy._symbol, utc_ts)
        if existing:
            return existing, None

        # 2. Configurar contexto de BTC diario
        self._strategy.set_btc_daily_context(btc_daily_candles)

        # 3. Evaluar Gates de Strategy C
        filters_snapshot, trade_signal = self._strategy.evaluate_gates(candles_1h, idx)

        # 4. Construir Snapshot de Régimen de Mercado
        btc_4h_mom = "BEARISH"
        if btc_4h_candles and len(btc_4h_candles) >= 50:
            btc_4h_closes = [c.close for c in btc_4h_candles]
            e20 = calculate_ema(btc_4h_closes, 20)[-1]
            e50 = calculate_ema(btc_4h_closes, 50)[-1]
            if e20 and e50 and e20 > e50:
                btc_4h_mom = "BULLISH"

        regime_snapshot = MarketRegimeSnapshot(
            btc_daily_state="BULLISH" if filters_snapshot.btc_macro_bullish else "BEARISH",
            btc_4h_momentum=btc_4h_mom,
            volatility_regime="EXPANSION" if filters_snapshot.range_filter_passed else "COMPRESSION",
            volume_regime="HIGH_RELATIVE_VOL" if filters_snapshot.volume_p70_passed else "NORMAL_LOW",
        )

        # 5. Snapshot del Portfolio Risk Engine
        open_pos_count = self._broker.get_open_positions_count() if self._broker else 0
        total_exp_usd = self._broker.get_total_exposure_usd() if self._broker else Decimal("0")
        risk_snapshot = self._risk_engine.get_snapshot(
            current_time=utc_ts,
            open_positions_count=open_pos_count,
            total_exposure_usd=total_exp_usd,
        )

        # 6. Determinar Acción y Razones Estructuradas
        decision_id = f"dec_{uuid.uuid4().hex[:12]}"
        config_hash = self._strategy.get_config_hash()

        prev_day_date = utc_ts.date()
        btc_prev_candle = next((c for c in btc_daily_candles if c.timestamp.date() < prev_day_date), None)
        recent_vols = [c.volume for c in candles_1h[max(0, idx - 100) : idx]]
        data_hash = self._compute_data_snapshot_hash(candle, btc_prev_candle, recent_vols)

        suggested_entry: Decimal | None = None
        suggested_sl: Decimal | None = None
        suggested_tp: Decimal | None = None
        suggested_qty: Decimal | None = None

        if not filters_snapshot.all_gates_passed:
            action = DecisionAction.BLOCKED_BY_STRATEGY
            lifecycle = LifecycleEvent.SIGNAL_GENERATED
            why_signal = "Incomplete technical breakout pattern"
            why_allowed = "None"
            why_blocked = self._format_blocked_gates(filters_snapshot)
        else:
            suggested_entry = trade_signal.price if trade_signal else candle.close
            suggested_sl = trade_signal.stop_loss if trade_signal else None
            suggested_tp = trade_signal.take_profit if trade_signal else None

            # Calcular tamaño de posición
            risk_pct = self._risk_engine.get_effective_risk_pct()
            if suggested_sl:
                suggested_qty = self._strategy.calculate_position_size(
                    account_equity=self._risk_engine.current_equity,
                    entry_price=suggested_entry,
                    stop_loss_price=suggested_sl,
                    risk_pct=risk_pct,
                )

            if not risk_snapshot.risk_allowed:
                action = DecisionAction.BLOCKED_BY_RISK
                lifecycle = LifecycleEvent.RISK_DECISION_BLOCKED
                why_signal = "Valid 20-bar structural breakout with volume and range maturity"
                why_allowed = "Passed all Strategy C gates"
                why_blocked = risk_snapshot.rejection_reason or "Blocked by risk limits"
            else:
                action = DecisionAction.SIGNAL_GENERATED
                lifecycle = LifecycleEvent.RISK_DECISION_ALLOWED
                why_signal = "Valid 20-bar structural breakout with volume expansion and range maturity"
                why_allowed = "Passed all Strategy C gates and Risk Engine checks"
                why_blocked = "None"

        # 7. Construir DecisionObject Inmutable
        decision = DecisionObject(
            decision_id=decision_id,
            timestamp=utc_ts,
            symbol=self._strategy._symbol,
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
            suggested_entry_price=suggested_entry,
            suggested_stop_loss=suggested_sl,
            suggested_take_profit=suggested_tp,
            suggested_quantity=suggested_qty,
            data_snapshot_hash=data_hash,
        )

        # 8. Persistir Decisión (Idempotente)
        self._persistence.save_decision(decision)

        # 9. Ejecutar Paper Broker si aplica
        new_position: PaperPosition | None = None
        if (
            execute_paper
            and self._broker
            and action == DecisionAction.SIGNAL_GENERATED
            and suggested_entry
            and suggested_sl
            and suggested_tp
            and suggested_qty
        ):
            _, _, new_position = self._broker.execute_paper_order(
                decision_id=decision.decision_id,
                symbol=decision.symbol,
                timestamp=utc_ts,
                signal_price=suggested_entry,
                stop_loss=suggested_sl,
                take_profit=suggested_tp,
                quantity=suggested_qty,
                risk_pct_used=self._risk_engine.get_effective_risk_pct(),
            )

        return decision, new_position

    def _format_blocked_gates(self, f: FilterEvaluationSnapshot) -> str:
        failed = []
        if not f.price_above_ema100:
            failed.append("Close <= EMA100")
        if not f.breakout_20_high:
            failed.append("Close <= Resistencia_20")
        if not f.close_position_passed:
            failed.append(f"Posición_Cierre ({f.close_position_ratio:.2f} < 0.65)")
        if not f.volume_sma20_passed:
            failed.append("Volumen < 1.20x SMA20")
        if not f.btc_macro_bullish:
            failed.append(f"BTC[D-1] ({f.btc_daily_close_prev:.0f}) <= EMA50 ({f.btc_daily_ema50_prev:.0f})")
        if not f.volume_p70_passed:
            failed.append(f"Volumen < P70 ({f.volume_p70_threshold:.0f})")
        if not f.range_filter_passed:
            failed.append(f"Rango_Previo ({f.range_atr_ratio:.2f}x < 4.0x ATR)")
        return ", ".join(failed) if failed else "Unknown"
