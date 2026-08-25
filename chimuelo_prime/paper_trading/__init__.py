"""Módulo de Paper Trading y Broker Virtual para Chimuelo Prime.

Permite simular operaciones en tiempo real o sobre feeds de velas con
balance virtual, ejecución con slippage/fees, gestión de posiciones con SL/TP
y despacho de alertas mediante AlertManager.
"""

from __future__ import annotations

from chimuelo_prime.paper_trading.engine import (
    PaperTradingConfig,
    PaperTradingCycleResult,
    PaperTradingEngine,
)
from chimuelo_prime.paper_trading.virtual_broker import (
    PaperTradeExecution,
    VirtualBroker,
    VirtualBrokerState,
)

__all__ = [
    "PaperTradeExecution",
    "VirtualBroker",
    "VirtualBrokerState",
    "PaperTradingConfig",
    "PaperTradingCycleResult",
    "PaperTradingEngine",
]
