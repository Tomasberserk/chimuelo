"""Configuración Versionada y Centralizada del Strategy Router (Fase 3).

Define todos los umbrales de histéresis, tiempos de dwell, períodos de enfriamiento
y vectores de ponderación de hipótesis (research priors) para la evaluación causal
de compatibilidad multiestrategia (Alpha Motors A, B, C y D).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RouterConfig:
    """Configuración cuantitativa congelada de la Fase 3 (Research Priors).

    Nota metodológica: Los pesos asignados a cada estrategia representan hipótesis
    estructurales de compatibilidad (RegimeCompatibilityScore), no pesos optimizados
    o validados fuera de muestra.
    """

    VERSION: str = "v0.1.0-research"

    # ==========================================================================
    # 1. PARÁMETROS DE LA MÁQUINA DE ESTADOS FINITA (FSM) E HISTÉRESIS
    # ==========================================================================
    arm_threshold: Decimal = Decimal("0.70")
    disarm_threshold: Decimal = Decimal("0.45")
    min_dwell_bars: int = 3
    cooldown_bars: int = 6
    ambiguity_threshold: Decimal = Decimal("0.15")

    # ==========================================================================
    # 2. VECTORES DE PONDERACIÓN POR ESTRATEGIA (HIPÓTESIS ESTRUCTURALES)
    # Cada conjunto de pesos suma exactamente 1.000.
    # ==========================================================================

    # --- Estrategia A: Volatility Squeeze ---
    w_A_volatility: Decimal = Decimal("0.35")
    w_A_transition: Decimal = Decimal("0.25")
    w_A_participation: Decimal = Decimal("0.20")
    w_A_structure: Decimal = Decimal("0.10")
    w_A_trend: Decimal = Decimal("0.10")
    w_A_derivatives: Decimal = Decimal("0.00")

    # --- Estrategia B: Deep Pullback ---
    w_B_trend: Decimal = Decimal("0.35")
    w_B_structure: Decimal = Decimal("0.25")
    w_B_participation: Decimal = Decimal("0.20")
    w_B_volatility: Decimal = Decimal("0.15")
    w_B_transition: Decimal = Decimal("0.05")
    w_B_derivatives: Decimal = Decimal("0.00")

    # --- Estrategia C: Liquidity Sweep (Motor Central - 76.5% Rango) ---
    w_C_structure: Decimal = Decimal("0.35")
    w_C_transition: Decimal = Decimal("0.25")
    w_C_participation: Decimal = Decimal("0.20")
    w_C_trend: Decimal = Decimal("0.15")
    w_C_volatility: Decimal = Decimal("0.05")
    w_C_derivatives: Decimal = Decimal("0.00")

    # --- Estrategia D: Derivatives Exhaustion (Especialista de Estrés) ---
    w_D_derivatives: Decimal = Decimal("0.40")
    w_D_volatility: Decimal = Decimal("0.25")
    w_D_participation: Decimal = Decimal("0.20")
    w_D_transition: Decimal = Decimal("0.10")
    w_D_trend: Decimal = Decimal("0.05")
    w_D_structure: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        """Valida rigurosamente la normalización de pesos (sum == 1.000) en inicialización."""
        sum_a = (
            self.w_A_volatility
            + self.w_A_transition
            + self.w_A_participation
            + self.w_A_structure
            + self.w_A_trend
            + self.w_A_derivatives
        )
        sum_b = (
            self.w_B_trend
            + self.w_B_structure
            + self.w_B_participation
            + self.w_B_volatility
            + self.w_B_transition
            + self.w_B_derivatives
        )
        sum_c = (
            self.w_C_structure
            + self.w_C_transition
            + self.w_C_participation
            + self.w_C_trend
            + self.w_C_volatility
            + self.w_C_derivatives
        )
        sum_d = (
            self.w_D_derivatives
            + self.w_D_volatility
            + self.w_D_participation
            + self.w_D_transition
            + self.w_D_trend
            + self.w_D_structure
        )

        one = Decimal("1.000")
        if abs(sum_a - one) > Decimal("0.0001"):
            raise ValueError(f"Pesos de Estrategia A deben sumar 1.000, suman {sum_a}")
        if abs(sum_b - one) > Decimal("0.0001"):
            raise ValueError(f"Pesos de Estrategia B deben sumar 1.000, suman {sum_b}")
        if abs(sum_c - one) > Decimal("0.0001"):
            raise ValueError(f"Pesos de Estrategia C deben sumar 1.000, suman {sum_c}")
        if abs(sum_d - one) > Decimal("0.0001"):
            raise ValueError(f"Pesos de Estrategia D deben sumar 1.000, suman {sum_d}")
