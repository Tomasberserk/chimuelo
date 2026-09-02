"""Módulo de Telemetría Acumulativa y Monitoreo de Ejecución para Live Paper Trading."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.paper_trading.decision_models import (
    DecisionAction,
    DecisionObject,
    PaperFill,
    PaperPosition,
)


class PaperTelemetryCollector:
    """Recolector central de métricas acumulativas de infraestructura y trading."""

    def __init__(self) -> None:
        self._start_time = datetime.now(UTC)
        self._log = get_logger(__name__)

        # Contadores de decisiones
        self.total_evaluations: int = 0
        self.signals_generated: int = 0
        self.blocked_by_strategy: int = 0
        self.blocked_by_risk: int = 0

        # Contadores de órdenes y ejecuciones
        self.orders_created: int = 0
        self.fills_executed: int = 0
        self.positions_opened: int = 0
        self.positions_closed: int = 0

        # Métricas de ejecución y fricción
        self.total_slippage_usd: Decimal = Decimal("0")
        self.total_fees_usd: Decimal = Decimal("0")
        self.closed_positions: list[PaperPosition] = []

        # Métricas de infraestructura
        self.ws_reconnects: int = 0
        self.rest_fallbacks: int = 0
        self.stale_candles_detected: int = 0
        self.duplicate_events_detected: int = 0
        self.latencies_ms: list[float] = []

    def record_decision(self, decision: DecisionObject) -> None:
        """Registra una evaluación de decisión."""
        self.total_evaluations += 1
        if decision.action == DecisionAction.SIGNAL_GENERATED:
            self.signals_generated += 1
        elif decision.action == DecisionAction.BLOCKED_BY_RISK:
            self.blocked_by_risk += 1
        elif decision.action == DecisionAction.NO_SIGNAL:
            self.blocked_by_strategy += 1

    def record_fill(self, fill: PaperFill) -> None:
        """Registra la ejecución simulada de un fill."""
        self.fills_executed += 1
        slippage_cost = abs(fill.fill_price - fill.signal_price) * fill.quantity
        self.total_slippage_usd += slippage_cost
        self.total_fees_usd += fill.fee_usd

    def record_closed_position(self, pos: PaperPosition) -> None:
        """Registra una posición cerrada."""
        self.positions_closed += 1
        self.closed_positions.append(pos)
        if pos.fee_exit:
            self.total_fees_usd += pos.fee_exit

    def record_network_event(
        self, event_type: str, latency_ms: float | None = None
    ) -> None:
        """Registra eventos de red o infraestructura."""
        if event_type == "RECONNECT":
            self.ws_reconnects += 1
        elif event_type == "REST_FALLBACK":
            self.rest_fallbacks += 1
        elif event_type == "STALE_CANDLE":
            self.stale_candles_detected += 1
        elif event_type == "DUPLICATE_EVENT":
            self.duplicate_events_detected += 1

        if latency_ms is not None:
            self.latencies_ms.append(latency_ms)

    def get_summary(self, current_equity: Decimal = Decimal("100.00"), hwm: Decimal = Decimal("100.00")) -> dict[str, Any]:
        """Calcula el resumen de métricas acumulativas cuantitativas y de infraestructura."""
        now = datetime.now(UTC)
        uptime_hours = (now - self._start_time).total_seconds() / 3600.0

        winning_trades = [p for p in self.closed_positions if (p.net_pnl or Decimal("0")) > Decimal("0")]
        losing_trades = [p for p in self.closed_positions if (p.net_pnl or Decimal("0")) <= Decimal("0")]

        total_closed = len(self.closed_positions)
        win_rate_pct = (len(winning_trades) / total_closed * 100.0) if total_closed > 0 else 0.0

        gross_gains = sum((p.gross_pnl for p in winning_trades if p.gross_pnl), Decimal("0"))
        gross_losses = sum((abs(p.gross_pnl) for p in losing_trades if p.gross_pnl), Decimal("0"))
        profit_factor = (float(gross_gains) / float(gross_losses)) if gross_losses > Decimal("0") else (999.0 if gross_gains > Decimal("0") else 0.0)

        net_pnls = [(p.net_pnl or Decimal("0")) for p in self.closed_positions]
        total_net_pnl = sum(net_pnls, Decimal("0"))
        expectancy = (float(total_net_pnl) / total_closed) if total_closed > 0 else 0.0

        r_multiples = [float(p.r_multiple or 0) for p in self.closed_positions]
        avg_r = (sum(r_multiples) / len(r_multiples)) if r_multiples else 0.0

        max_dd_pct = float((hwm - current_equity) / hwm * Decimal("100")) if hwm > Decimal("0") else 0.0
        avg_latency = (sum(self.latencies_ms) / len(self.latencies_ms)) if self.latencies_ms else 0.0

        return {
            "uptime_hours": round(uptime_hours, 2),
            "total_evaluations": self.total_evaluations,
            "signals_generated": self.signals_generated,
            "blocked_by_strategy": self.blocked_by_strategy,
            "blocked_by_risk": self.blocked_by_risk,
            "positions_closed": total_closed,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate_pct": round(win_rate_pct, 2),
            "profit_factor": round(profit_factor, 2),
            "expectancy_usd": round(expectancy, 4),
            "average_r": round(avg_r, 4),
            "total_net_pnl_usd": str(total_net_pnl),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "total_slippage_usd": str(self.total_slippage_usd),
            "total_fees_usd": str(self.total_fees_usd),
            "infrastructure": {
                "ws_reconnects": self.ws_reconnects,
                "rest_fallbacks": self.rest_fallbacks,
                "stale_candles": self.stale_candles_detected,
                "duplicate_events": self.duplicate_events_detected,
                "avg_latency_ms": round(avg_latency, 2),
            },
        }

    def export_summary_json(self, file_path: str = "data/reports/live_paper_telemetry.json") -> None:
        """Exporta el reporte a JSON en disco."""
        summary = self.get_summary()
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
