"""Portfolio Risk Engine y Máquina de Estados para Live Paper Trading."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from chimuelo_prime.paper_trading.decision_models import (
    RiskStateEnum,
    RiskStateSnapshot,
    ensure_utc_aware,
)


class PortfolioRiskEngine:
    """Controlador central de riesgo de portafolio y disyuntor (Circuit Breaker)."""

    # Parámetros estrictos de riesgo
    MAX_DAILY_DRAWDOWN_PCT: Decimal = Decimal("3.0")
    MAX_PEAK_DRAWDOWN_PCT: Decimal = Decimal("15.0")
    MAX_CONSECUTIVE_LOSSES: int = 4
    MAX_SIMULTANEOUS_POSITIONS: int = 2
    MAX_TOTAL_EXPOSURE_PCT: Decimal = Decimal("60.0")
    BASE_RISK_PER_TRADE_PCT: Decimal = Decimal("0.025")  # 2.5%
    REDUCED_RISK_PER_TRADE_PCT: Decimal = Decimal("0.0125")  # 1.25%

    def __init__(
        self,
        initial_equity: Decimal = Decimal("100.00"),
        current_state: RiskStateEnum = RiskStateEnum.NORMAL,
    ) -> None:
        self._initial_equity = initial_equity
        self._current_equity = initial_equity
        self._high_water_mark = initial_equity
        self._daily_start_equity = initial_equity
        self._current_day: date | None = None
        self._consecutive_losses: int = 0
        self._current_state = current_state
        self._cooldown_until: datetime | None = None

    @property
    def current_state(self) -> RiskStateEnum:
        return self._current_state

    @property
    def current_equity(self) -> Decimal:
        return self._current_equity

    @property
    def high_water_mark(self) -> Decimal:
        return self._high_water_mark

    @property
    def daily_start_equity(self) -> Decimal:
        return self._daily_start_equity

    @property
    def current_day(self) -> date | None:
        return self._current_day

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    @property
    def cooldown_until(self) -> datetime | None:
        return self._cooldown_until

    def update_equity_and_day(self, equity: Decimal, current_time: datetime) -> None:
        """Actualiza el capital, HWM y resetea el drawdown diario a las 00:00 UTC."""
        utc_dt = ensure_utc_aware(current_time)
        self._current_equity = equity

        # Actualizar High-Water Mark
        if self._current_equity > self._high_water_mark:
            self._high_water_mark = self._current_equity

        # Control de día para Daily Drawdown (medianoche UTC)
        if self._current_day is None:
            self._current_day = utc_dt.date()
        elif utc_dt.date() > self._current_day:
            self._current_day = utc_dt.date()
            self._daily_start_equity = self._current_equity
            if self._current_state == RiskStateEnum.CIRCUIT_BREAKER_DAILY:
                self._current_state = RiskStateEnum.COOLDOWN
                self._cooldown_until = utc_dt.replace(hour=0, minute=0, second=0)

        # Chequear si salimos de Cooldown
        if self._current_state == RiskStateEnum.COOLDOWN:
            if self._cooldown_until and utc_dt >= self._cooldown_until:
                self._current_state = RiskStateEnum.NORMAL
                self._cooldown_until = None

        self._check_state_transitions()

    def record_trade_result(self, net_pnl: Decimal, exit_time: datetime) -> None:
        """Registra el resultado de un trade cerrado y actualiza la racha de pérdidas."""
        utc_dt = ensure_utc_aware(exit_time)
        if self._current_day is None:
            self._current_day = utc_dt.date()
        elif utc_dt.date() > self._current_day:
            self._current_day = utc_dt.date()
            self._daily_start_equity = self._current_equity

        self._current_equity += net_pnl
        if self._current_equity > self._high_water_mark:
            self._high_water_mark = self._current_equity

        if net_pnl <= Decimal("0"):
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0
            if self._current_state == RiskStateEnum.REDUCED_SIZING:
                self._current_state = RiskStateEnum.NORMAL

        self._check_state_transitions()

    def _check_state_transitions(self) -> None:
        """Evalúa las transiciones de la máquina de estados según métricas de drawdown."""
        # 1. Peak-to-Trough Drawdown
        peak_dd_pct = Decimal("0")
        if self._high_water_mark > Decimal("0"):
            peak_dd_pct = ((self._high_water_mark - self._current_equity) / self._high_water_mark) * Decimal("100")

        if peak_dd_pct >= self.MAX_PEAK_DRAWDOWN_PCT:
            self._current_state = RiskStateEnum.CIRCUIT_BREAKER_MAX_DD
            return

        # 2. Daily Drawdown
        daily_dd_pct = Decimal("0")
        if self._daily_start_equity > Decimal("0"):
            daily_dd_pct = ((self._daily_start_equity - self._current_equity) / self._daily_start_equity) * Decimal("100")

        if daily_dd_pct >= self.MAX_DAILY_DRAWDOWN_PCT and self._current_state != RiskStateEnum.CIRCUIT_BREAKER_MAX_DD:
            self._current_state = RiskStateEnum.CIRCUIT_BREAKER_DAILY
            return

        # 3. Racha de pérdidas
        if self._consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES:
            if self._current_state == RiskStateEnum.NORMAL:
                self._current_state = RiskStateEnum.REDUCED_SIZING

    def get_snapshot(
        self,
        current_time: datetime,
        open_positions_count: int = 0,
        total_exposure_usd: Decimal = Decimal("0"),
        proposed_trade_notional: Decimal = Decimal("0"),
    ) -> RiskStateSnapshot:
        """Genera el snapshot inmutable del estado de riesgo con verificación de exposición proyectada."""
        utc_dt = ensure_utc_aware(current_time)
        self.update_equity_and_day(self._current_equity, utc_dt)

        peak_dd_pct = Decimal("0")
        if self._high_water_mark > Decimal("0"):
            peak_dd_pct = ((self._high_water_mark - self._current_equity) / self._high_water_mark) * Decimal("100")

        daily_dd_pct = Decimal("0")
        if self._daily_start_equity > Decimal("0"):
            daily_dd_pct = ((self._daily_start_equity - self._current_equity) / self._daily_start_equity) * Decimal("100")

        # Exposición actual y proyectada
        current_exposure_pct = Decimal("0")
        projected_exposure_usd = total_exposure_usd + proposed_trade_notional
        projected_exposure_pct = Decimal("0")

        if self._current_equity > Decimal("0"):
            current_exposure_pct = (total_exposure_usd / self._current_equity) * Decimal("100")
            projected_exposure_pct = (projected_exposure_usd / self._current_equity) * Decimal("100")

        risk_allowed = True
        rejection_reason = None

        if self._current_state in (RiskStateEnum.CIRCUIT_BREAKER_DAILY, RiskStateEnum.CIRCUIT_BREAKER_MAX_DD):
            risk_allowed = False
            rejection_reason = f"Circuit Breaker activo ({self._current_state.value})"
        elif open_positions_count >= self.MAX_SIMULTANEOUS_POSITIONS:
            risk_allowed = False
            rejection_reason = f"Límite de posiciones simultáneas alcanzado ({open_positions_count}/{self.MAX_SIMULTANEOUS_POSITIONS})"
        elif projected_exposure_pct > self.MAX_TOTAL_EXPOSURE_PCT:
            risk_allowed = False
            rejection_reason = (
                f"Límite de exposición total proyectada excedido "
                f"({projected_exposure_pct:.1f}% > {self.MAX_TOTAL_EXPOSURE_PCT}%)"
            )

        return RiskStateSnapshot(
            current_state=self._current_state,
            high_water_mark=self._high_water_mark,
            current_equity=self._current_equity,
            daily_drawdown_pct=daily_dd_pct.quantize(Decimal("0.01")),
            peak_to_trough_drawdown_pct=peak_dd_pct.quantize(Decimal("0.01")),
            consecutive_losses_count=self._consecutive_losses,
            open_positions_count=open_positions_count,
            total_exposure_pct=projected_exposure_pct.quantize(Decimal("0.01")),
            risk_allowed=risk_allowed,
            rejection_reason=rejection_reason,
        )

    def get_effective_risk_pct(self) -> Decimal:
        """Retorna el porcentaje de riesgo por trade según el estado de racha."""
        if self._current_state == RiskStateEnum.REDUCED_SIZING:
            return self.REDUCED_RISK_PER_TRADE_PCT
        return self.BASE_RISK_PER_TRADE_PCT

    def restore_state(
        self,
        equity: Decimal,
        high_water_mark: Decimal,
        daily_start_equity: Decimal,
        consecutive_losses: int,
        current_state: RiskStateEnum,
        last_day: date | None = None,
        cooldown_until: datetime | None = None,
    ) -> None:
        """Restaura el estado exacto persistido tras reinicio."""
        self._current_equity = equity
        self._high_water_mark = high_water_mark
        self._daily_start_equity = daily_start_equity
        self._consecutive_losses = consecutive_losses
        self._current_state = current_state
        self._current_day = last_day
        self._cooldown_until = ensure_utc_aware(cooldown_until) if cooldown_until else None
