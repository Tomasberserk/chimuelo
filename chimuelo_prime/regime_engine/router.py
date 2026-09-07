"""Strategy Router: Asignación Causal de Permisos Multi-Estrategia (Fase 3).

Implementa la Máquina de Estados Finita (FSM) desacoplada para los 4 Alpha Motors:
- DISABLED: Score insuficiente o compuerta dura fallida.
- ARMED: Score >= 0.70 y Hard Gate superado; estrategia autorizada a vigilar gatillo.
- ACTIVE: Representa estrictamente una posición abierta en mercado.
- COOLDOWN: Enfriamiento forzoso post-salida por N barras.

Incorpora:
- Histéresis causal ([0.45, 0.70)).
- Minimum Dwell Time (t_arm = 0, Dwell_t = barras cerradas desde t_arm).
- Veto macroeconómico Hermes como compuerta exclusiva de entrada (MacroEntryVeto).
- Concurrencia multiestrategia (sin argmax global ni winner-takes-all).
- Filtrado direccional y registro forense estructurado.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from chimuelo_prime.regime_engine.models import (
    AlphaMotorId,
    DirectionalScore,
    ForensicDecisionLog,
    MarketStateVector,
    NoTradeReasonCode,
    RouterEvaluationResult,
    RouterStrategyState,
    StrategyEvaluationLog,
    TradeCandidate,
    TradeDirection,
)
from chimuelo_prime.regime_engine.router_config import RouterConfig
from chimuelo_prime.regime_engine.scoring import StrategyCompatibilityScorer


class StrategyRouter:
    """Router Cuantitativo para la autorización y control FSM de Alpha Motors."""

    def __init__(
        self,
        config: RouterConfig | None = None,
        scorer: StrategyCompatibilityScorer | None = None,
    ) -> None:
        self.config = config or RouterConfig()
        self.scorer = scorer or StrategyCompatibilityScorer(config=self.config)

        # Estado interno de la FSM por cada estrategia
        self.strategy_states: dict[AlphaMotorId, RouterStrategyState] = {
            strat: RouterStrategyState.DISABLED for strat in AlphaMotorId
        }
        # Contador de barras en estado ARMED desde la activación (t_arm = 0)
        self.dwell_counters: dict[AlphaMotorId, int] = {
            strat: 0 for strat in AlphaMotorId
        }
        # Contador de barras restantes en estado COOLDOWN
        self.cooldown_counters: dict[AlphaMotorId, int] = {
            strat: 0 for strat in AlphaMotorId
        }

    def reset(self) -> None:
        """Reinicia el estado de la FSM y todos los contadores a valores iniciales."""
        for strat in AlphaMotorId:
            self.strategy_states[strat] = RouterStrategyState.DISABLED
            self.dwell_counters[strat] = 0
            self.cooldown_counters[strat] = 0

    @staticmethod
    def _has_active_position(active_positions: Any, strategy_id: AlphaMotorId) -> bool:
        """Verifica causalmente si existe una posición de mercado abierta para la estrategia."""
        if not active_positions:
            return False
        if isinstance(active_positions, dict):
            return bool(active_positions.get(strategy_id))
        if isinstance(active_positions, set | list | tuple):
            return strategy_id in active_positions
        return False

    def calculate_regime_confidence(
        self,
        scores: dict[AlphaMotorId, tuple[DirectionalScore, bool]],
    ) -> Decimal:
        """Calcula la métrica de confianza de régimen: Score_max - Score_second.

        Evita decisiones en regímenes ambiguos donde dos o más estrategias tienen
        puntuaciones idénticas sin ventaja clara.
        """
        combined_scores = sorted(
            [score.combined_score for score, _ in scores.values()],
            reverse=True,
        )
        if len(combined_scores) < 2:
            return Decimal("1.0000")

        confidence = combined_scores[0] - combined_scores[1]
        clamped = max(Decimal("0.0000"), min(Decimal("1.0000"), confidence))
        return round(clamped, 4)

    def evaluate(
        self,
        symbol: str,
        market_state: MarketStateVector,
        active_positions: Any = None,
        hermes_entry_veto: bool = False,
        derivative_event: bool = False,
    ) -> RouterEvaluationResult:
        """Evaluación determinista y causal de compatibilidad y transición FSM.

        No genera órdenes; determina qué motores tienen permiso para buscar su propio edge.
        """
        # 1. Puntuación desacoplada (Soft Scores + Hard Gates)
        scores = self.scorer.score_all_strategies(market_state, derivative_event=derivative_event)
        regime_conf = self.calculate_regime_confidence(scores)

        strategy_evals: dict[AlphaMotorId, StrategyEvaluationLog] = {}

        for strat_id in AlphaMotorId:
            state_before = self.strategy_states[strat_id]
            dwell_before = self.dwell_counters[strat_id]
            cooldown_before = self.cooldown_counters[strat_id]

            dir_score, hard_gate_passed = scores[strat_id]
            score_val = dir_score.combined_score
            has_pos = self._has_active_position(active_positions, strat_id)

            state_after: RouterStrategyState
            dwell_after: int
            cooldown_remaining: int
            authorized: bool
            rejection_reason: NoTradeReasonCode | None = None

            # ------------------------------------------------------------------
            # CASO 1: LA ESTRATEGIA TIENE UNA POSICIÓN ACTIVA EN MERCADO
            # ------------------------------------------------------------------
            if has_pos:
                # ACTIVE representa estrictamente posición abierta
                state_after = RouterStrategyState.ACTIVE
                dwell_after = dwell_before + 1 if state_before == RouterStrategyState.ACTIVE else 0
                cooldown_remaining = 0
                authorized = False  # Ya en posición; no abre posición concurrente
                rejection_reason = None

            # ------------------------------------------------------------------
            # CASO 2: POSICIÓN SE CERRÓ EN ESTA BARRA (ACTIVE -> COOLDOWN)
            # ------------------------------------------------------------------
            elif state_before == RouterStrategyState.ACTIVE and not has_pos:
                state_after = RouterStrategyState.COOLDOWN
                dwell_after = 0
                cooldown_remaining = self.config.cooldown_bars
                authorized = False
                rejection_reason = NoTradeReasonCode.COOLDOWN_ACTIVE

            # ------------------------------------------------------------------
            # CASO 3: EN PERÍODO DE ENFRIAMIENTO (COOLDOWN)
            # ------------------------------------------------------------------
            elif state_before == RouterStrategyState.COOLDOWN:
                if cooldown_before > 1:
                    cooldown_remaining = cooldown_before - 1
                    state_after = RouterStrategyState.COOLDOWN
                    dwell_after = 0
                    authorized = False
                    rejection_reason = NoTradeReasonCode.COOLDOWN_ACTIVE
                else:
                    # Enfriamiento completado: transición limpia a DISABLED
                    cooldown_remaining = 0
                    state_after = RouterStrategyState.DISABLED
                    dwell_after = 0
                    authorized = False
                    rejection_reason = None

            # ------------------------------------------------------------------
            # CASO 4: ESTRATEGIA PREVIAMENTE EN VIGILANCIA (ARMED)
            # ------------------------------------------------------------------
            elif state_before == RouterStrategyState.ARMED:
                # Invalidador duro: Hard Gate fallido causa desarme inmediato
                if not hard_gate_passed:
                    state_after = RouterStrategyState.DISABLED
                    dwell_after = 0
                    cooldown_remaining = 0
                    authorized = False
                    rejection_reason = NoTradeReasonCode.NO_ALPHA_COMPATIBILITY

                # Pérdida de compatibilidad (< disarm_threshold)
                elif score_val < self.config.disarm_threshold:
                    # Protección por Minimum Dwell Time (Dwell >= min_dwell_bars para desarmar)
                    if dwell_before >= self.config.min_dwell_bars:
                        state_after = RouterStrategyState.DISABLED
                        dwell_after = 0
                        cooldown_remaining = 0
                        authorized = False
                        rejection_reason = NoTradeReasonCode.NO_ALPHA_COMPATIBILITY
                    else:
                        # Retenido en ARMED por Dwell Time mínimo
                        state_after = RouterStrategyState.ARMED
                        dwell_after = dwell_before + 1
                        cooldown_remaining = 0
                        authorized = not hermes_entry_veto
                        rejection_reason = (
                            NoTradeReasonCode.HERMES_VETO if hermes_entry_veto else None
                        )

                # Score en banda de histéresis [0.45, 0.70) o superior (>= 0.70)
                else:
                    state_after = RouterStrategyState.ARMED
                    dwell_after = dwell_before + 1
                    cooldown_remaining = 0
                    authorized = not hermes_entry_veto
                    rejection_reason = (
                        NoTradeReasonCode.HERMES_VETO if hermes_entry_veto else None
                    )

            # ------------------------------------------------------------------
            # CASO 5: ESTRATEGIA DESACTIVADA (DISABLED)
            # ------------------------------------------------------------------
            else:
                can_arm = (score_val >= self.config.arm_threshold) and hard_gate_passed
                if can_arm:
                    if hermes_entry_veto:
                        # Veto de entrada macroeconómico impide armar
                        state_after = RouterStrategyState.DISABLED
                        dwell_after = 0
                        cooldown_remaining = 0
                        authorized = False
                        rejection_reason = NoTradeReasonCode.HERMES_VETO
                    else:
                        # Transición DISABLED -> ARMED: t_arm es la barra actual (dwell = 0)
                        state_after = RouterStrategyState.ARMED
                        dwell_after = 0
                        cooldown_remaining = 0
                        authorized = True
                        rejection_reason = None
                else:
                    state_after = RouterStrategyState.DISABLED
                    dwell_after = 0
                    cooldown_remaining = 0
                    authorized = False
                    rejection_reason = NoTradeReasonCode.NO_ALPHA_COMPATIBILITY

            # Actualización inmutable del estado interno
            self.strategy_states[strat_id] = state_after
            self.dwell_counters[strat_id] = dwell_after
            self.cooldown_counters[strat_id] = cooldown_remaining

            strategy_evals[strat_id] = StrategyEvaluationLog(
                strategy_id=strat_id,
                state_before=state_before,
                state_after=state_after,
                score=dir_score,
                hard_gate_passed=hard_gate_passed,
                dwell_bars_before=dwell_before,
                dwell_bars_after=dwell_after,
                cooldown_remaining=cooldown_remaining,
                authorized_for_trigger=authorized,
                rejection_reason=rejection_reason,
            )

        armed_list = [
            s for s, st in self.strategy_states.items() if st == RouterStrategyState.ARMED
        ]
        active_list = [
            s for s, st in self.strategy_states.items() if st == RouterStrategyState.ACTIVE
        ]
        cooldown_list = [
            s for s, st in self.strategy_states.items() if st == RouterStrategyState.COOLDOWN
        ]

        has_authorized = any(
            log.authorized_for_trigger for log in strategy_evals.values()
        )
        global_action = "TRADE_PERMITTED" if (has_authorized or len(active_list) > 0) else "NO_TRADE"

        details = (
            f"Armed: {[s.value for s in armed_list]} | "
            f"Active: {[s.value for s in active_list]} | "
            f"Cooldown: {[s.value for s in cooldown_list]} | "
            f"RegimeConfidence: {regime_conf} | "
            f"HermesVeto: {hermes_entry_veto}"
        )

        return RouterEvaluationResult(
            timestamp=market_state.timestamp,
            symbol=symbol,
            market_state=market_state,
            strategy_evaluations=strategy_evals,
            armed_strategies=armed_list,
            active_strategies=active_list,
            cooldown_strategies=cooldown_list,
            hermes_entry_veto=hermes_entry_veto,
            global_action=global_action,
            details=details,
        )

    def filter_trade_candidates(
        self,
        candidates: Sequence[TradeCandidate],
        router_result: RouterEvaluationResult,
    ) -> tuple[list[TradeCandidate], list[ForensicDecisionLog]]:
        """Filtra y valida candidatos de trade propuestos por los Alpha Motors.

        Verifica:
        1. Estado ARMED de la estrategia emisora.
        2. Autorización de gatillo activa (sin Veto de Hermes).
        3. Aprobación direccional específica por Hard Gate.
        4. Umbral de ambigüedad de régimen.
        """
        approved_candidates: list[TradeCandidate] = []
        forensic_logs: list[ForensicDecisionLog] = []

        scores_dict = {
            s.value: log.score.combined_score
            for s, log in router_result.strategy_evaluations.items()
        }
        fsm_dict = {
            s.value: log.state_after
            for s, log in router_result.strategy_evaluations.items()
        }
        regime_conf = self.calculate_regime_confidence(
            {s: (log.score, log.hard_gate_passed) for s, log in router_result.strategy_evaluations.items()}
        )

        for cand in candidates:
            strat_log = router_result.strategy_evaluations.get(cand.strategy_id)
            if strat_log is None:
                forensic_logs.append(
                    ForensicDecisionLog(
                        timestamp=cand.timestamp,
                        symbol=cand.symbol,
                        decision_action="NO_TRADE",
                        reason_code=NoTradeReasonCode.NO_ALPHA_COMPATIBILITY,
                        market_state=router_result.market_state,
                        strategy_scores=scores_dict,
                        fsm_states=fsm_dict,
                        regime_confidence=regime_conf,
                        hermes_veto=router_result.hermes_entry_veto,
                        details=f"Candidate {cand.candidate_id}: Estrategia no registrada en evaluación.",
                    )
                )
                continue

            # 1. Enfriamiento activo
            if strat_log.state_after == RouterStrategyState.COOLDOWN:
                forensic_logs.append(
                    ForensicDecisionLog(
                        timestamp=cand.timestamp,
                        symbol=cand.symbol,
                        decision_action="NO_TRADE",
                        reason_code=NoTradeReasonCode.COOLDOWN_ACTIVE,
                        market_state=router_result.market_state,
                        strategy_scores=scores_dict,
                        fsm_states=fsm_dict,
                        regime_confidence=regime_conf,
                        hermes_veto=router_result.hermes_entry_veto,
                        details=f"Candidate {cand.candidate_id}: Estrategia en período de COOLDOWN forzoso.",
                    )
                )
                continue

            # 2. Estrategia desarmada / inactiva
            if strat_log.state_after == RouterStrategyState.DISABLED:
                forensic_logs.append(
                    ForensicDecisionLog(
                        timestamp=cand.timestamp,
                        symbol=cand.symbol,
                        decision_action="NO_TRADE",
                        reason_code=NoTradeReasonCode.NO_ALPHA_COMPATIBILITY,
                        market_state=router_result.market_state,
                        strategy_scores=scores_dict,
                        fsm_states=fsm_dict,
                        regime_confidence=regime_conf,
                        hermes_veto=router_result.hermes_entry_veto,
                        details=f"Candidate {cand.candidate_id}: Estrategia DISABLED (Score insuficiente).",
                    )
                )
                continue

            # 3. Veto macroeconómico de Hermes
            if router_result.hermes_entry_veto:
                forensic_logs.append(
                    ForensicDecisionLog(
                        timestamp=cand.timestamp,
                        symbol=cand.symbol,
                        decision_action="NO_TRADE",
                        reason_code=NoTradeReasonCode.HERMES_VETO,
                        market_state=router_result.market_state,
                        strategy_scores=scores_dict,
                        fsm_states=fsm_dict,
                        regime_confidence=regime_conf,
                        hermes_veto=True,
                        details=f"Candidate {cand.candidate_id}: Bloqueado por MacroEntryVeto de Hermes.",
                    )
                )
                continue

            # 4. Verificación de compuerta dura direccional
            dir_gate_passed = self.scorer.evaluate_hard_gate(
                strategy_id=cand.strategy_id,
                market_state=router_result.market_state,
                direction=cand.direction,
            )
            if not dir_gate_passed:
                forensic_logs.append(
                    ForensicDecisionLog(
                        timestamp=cand.timestamp,
                        symbol=cand.symbol,
                        decision_action="NO_TRADE",
                        reason_code=NoTradeReasonCode.NO_ALPHA_COMPATIBILITY,
                        market_state=router_result.market_state,
                        strategy_scores=scores_dict,
                        fsm_states=fsm_dict,
                        regime_confidence=regime_conf,
                        hermes_veto=router_result.hermes_entry_veto,
                        details=f"Candidate {cand.candidate_id}: Invalidación estructural para dirección {cand.direction.value}.",
                    )
                )
                continue

            # 5. Verificación de score direccional específico
            strat_directional_score = (
                strat_log.score.long_score
                if cand.direction == TradeDirection.LONG
                else strat_log.score.short_score
            )
            if strat_directional_score < self.config.disarm_threshold:
                forensic_logs.append(
                    ForensicDecisionLog(
                        timestamp=cand.timestamp,
                        symbol=cand.symbol,
                        decision_action="NO_TRADE",
                        reason_code=NoTradeReasonCode.NO_ALPHA_COMPATIBILITY,
                        market_state=router_result.market_state,
                        strategy_scores=scores_dict,
                        fsm_states=fsm_dict,
                        regime_confidence=regime_conf,
                        hermes_veto=router_result.hermes_entry_veto,
                        details=(
                            f"Candidate {cand.candidate_id}: Score direccional insuficiente "
                            f"({strat_directional_score} < {self.config.disarm_threshold})."
                        ),
                    )
                )
                continue

            # 6. Autorización plena confirmada
            approved_candidates.append(cand)
            forensic_logs.append(
                ForensicDecisionLog(
                    timestamp=cand.timestamp,
                    symbol=cand.symbol,
                    decision_action="TRADE_APPROVED",
                    reason_code="APPROVED",
                    market_state=router_result.market_state,
                    strategy_scores=scores_dict,
                    fsm_states=fsm_dict,
                    regime_confidence=regime_conf,
                    hermes_veto=False,
                    details=f"Candidate {cand.candidate_id} ({cand.strategy_id.value} {cand.direction.value}) APROBADO por Router.",
                )
            )

        return approved_candidates, forensic_logs

    def create_forensic_log(
        self,
        router_result: RouterEvaluationResult,
        decision_action: str = "NO_TRADE",
        reason_code: NoTradeReasonCode | str = NoTradeReasonCode.NO_TRIGGER,
        details: str = "",
    ) -> ForensicDecisionLog:
        """Genera un registro forense causal de la barra cuando no hay órdenes ejecutadas."""
        scores_dict = {
            s.value: log.score.combined_score
            for s, log in router_result.strategy_evaluations.items()
        }
        fsm_dict = {
            s.value: log.state_after
            for s, log in router_result.strategy_evaluations.items()
        }
        regime_conf = self.calculate_regime_confidence(
            {s: (log.score, log.hard_gate_passed) for s, log in router_result.strategy_evaluations.items()}
        )

        return ForensicDecisionLog(
            timestamp=router_result.timestamp,
            symbol=router_result.symbol,
            decision_action=decision_action,
            reason_code=reason_code,
            market_state=router_result.market_state,
            strategy_scores=scores_dict,
            fsm_states=fsm_dict,
            regime_confidence=regime_conf,
            hermes_veto=router_result.hermes_entry_veto,
            details=details or router_result.details,
        )
