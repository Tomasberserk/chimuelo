"""Tests de seguridad y Hard Kill Switch para VirtualBroker y Paper Trading."""

import inspect
import pytest
from decimal import Decimal

from chimuelo_prime.paper_trading.persistence import SQLitePersistenceBackend
from chimuelo_prime.paper_trading.virtual_broker import (
    RealCredentialsDetectedError,
    VirtualBroker,
)


def test_virtual_broker_rejects_real_credentials(tmp_path):
    """Verifica que el Virtual Broker aborte inmediatamente si se le inyectan credenciales reales."""
    db_path = tmp_path / "test_paper.db"
    persistence = SQLitePersistenceBackend(str(db_path))

    # Inyección de API Key debe fallar
    with pytest.raises(RealCredentialsDetectedError, match="SEGURIDAD CRÍTICA"):
        VirtualBroker(
            persistence=persistence,
            api_key="real_binance_api_key_12345",
        )

    # Inyección de API Secret debe fallar
    with pytest.raises(RealCredentialsDetectedError, match="SEGURIDAD CRÍTICA"):
        VirtualBroker(
            persistence=persistence,
            api_secret="real_binance_secret_67890",
        )


def test_zero_real_exchange_imports():
    """Verifica mediante introspección que VirtualBroker no importe módulos de ejecución real de órdenes."""
    import chimuelo_prime.paper_trading.virtual_broker as vb_module
    import chimuelo_prime.paper_trading.decision_engine as de_module
    import chimuelo_prime.paper_trading.live_runner as lr_module

    source_vb = inspect.getsource(vb_module)
    source_de = inspect.getsource(de_module)
    source_lr = inspect.getsource(lr_module)

    forbidden_patterns = [
        "chimuelo_prime.order_execution",
        "api/v3/order",
        "create_order",
        "send_signed_request",
        "BinanceExchangeClient",
    ]

    for pattern in forbidden_patterns:
        assert pattern not in source_vb, f"Violación de seguridad: '{pattern}' encontrado en virtual_broker.py"
        assert pattern not in source_de, f"Violación de seguridad: '{pattern}' encontrado en decision_engine.py"
        assert pattern not in source_lr, f"Violación de seguridad: '{pattern}' encontrado en live_runner.py"
