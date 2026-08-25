"""Tests para GridEngine (M5).

Cubre los 19 casos obligatorios de MARTA:
    7.  _setup() enruta a _initialize_new_grid cuando no hay niveles en DB.
    8.  _setup() enruta a _resume_existing_grid cuando hay niveles en DB.
    9.  _initialize_new_grid guarda N GridLevel en M3 (N = grid_levels).
    10. _initialize_new_grid coloca BUY para cada nivel bajo el precio actual.
    11. _initialize_new_grid no coloca BUY para niveles en o sobre el precio.
    12. _initialize_new_grid propaga GridCalculationError.
    13. _initialize_new_grid propaga PriceFetchError.
    14. _resume_existing_grid llama reconciler.reconcile(symbol).
    15. _resume_existing_grid coloca SELL faltante (BUY FILLED sin sell_order_id).
    16. _resume_existing_grid no actúa si el SELL ya está colocado.
    17. _resume_existing_grid no actúa si el BUY no está FILLED.
    18. _run_poll_cycle llama sync_order_status por cada orden abierta.
    19. _run_poll_cycle collect-and-continue: un fallo no detiene las demás.
    20. _run_poll_cycle llama _on_buy_filled cuando un BUY transiciona a FILLED.
    21. _run_poll_cycle llama _on_sell_filled cuando un SELL transiciona a FILLED.
    22. _on_buy_filled coloca SELL en level.upper_price.
    23. _on_buy_filled usa executed_qty del OrderStatusUpdate.
    24. _on_sell_filled llama _take_snapshot.
    25. _take_snapshot persiste Snapshot en M3.
    26. stop() activa el threading.Event.
    27. _shutdown llama cancel_all_open_orders.
    28. _shutdown no re-lanza AggregateCancellationError.
    29. _shutdown llama _take_snapshot aunque cancel falle.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from chimuelo_prime.grid_engine.engine import GridEngine
from chimuelo_prime.grid_engine.exceptions import GridCalculationError, PriceFetchError
from chimuelo_prime.grid_state.grid_state import GridState
from chimuelo_prime.grid_state.reconciler import Reconciler
from chimuelo_prime.grid_state.schema import GridLevel, OrderStatus, Snapshot
from chimuelo_prime.order_execution.exceptions import (
    AggregateCancellationError,
    StatusSyncError,
)
from chimuelo_prime.order_execution.executor import OrderExecutor
from chimuelo_prime.order_execution.lifecycle import OrderLifecycleManager
from chimuelo_prime.order_execution.models import OrderStatusUpdate, PlacedOrder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_placed_order(order_id: int, side: str = "BUY") -> PlacedOrder:
    return PlacedOrder(
        order_id=order_id,
        client_order_id=f"cid-{order_id}",
        symbol="SOLUSDT",
        side=side,
        price=Decimal("100.00"),
        orig_qty=Decimal("0.10"),
        executed_qty=Decimal("0.10"),
        status=OrderStatus.NEW,
        level_id=1,
        transact_time=_utcnow(),
    )


def _make_status_update(
    order_id: int,
    previous: OrderStatus,
    current: OrderStatus,
    status_changed: bool = True,
    executed_qty: Decimal = Decimal("0.10"),
) -> OrderStatusUpdate:
    return OrderStatusUpdate(
        order_id=order_id,
        symbol="SOLUSDT",
        previous_status=previous,
        current_status=current,
        executed_qty=executed_qty,
        synced_at=_utcnow(),
        status_changed=status_changed,
    )


def _make_open_order(order_id: int, side: str = "BUY") -> MagicMock:
    order = MagicMock()
    order.order_id = order_id
    order.side = side
    order.price = Decimal("100.00")
    order.qty = Decimal("0.10")
    order.status = OrderStatus.NEW.value
    return order


def _make_grid_level(
    level_id: int,
    buy_order_id: int | None = None,
    sell_order_id: int | None = None,
    buy_status: str = OrderStatus.NEW.value,
) -> MagicMock:
    level = MagicMock(spec=GridLevel)
    level.level_id = level_id
    level.symbol = "SOLUSDT"
    level.lower_price = Decimal("100.00")
    level.upper_price = Decimal("102.00")
    level.buy_order_id = buy_order_id
    level.sell_order_id = sell_order_id
    return level


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_grid_state() -> MagicMock:
    gs = MagicMock(spec=GridState)
    gs.get_open_orders.return_value = []
    gs.save_grid_level.side_effect = lambda level: _counter()  # replaced per test
    return gs


def _counter() -> int:
    if not hasattr(_counter, "_n"):
        _counter._n = 0  # type: ignore[attr-defined]
    _counter._n += 1  # type: ignore[attr-defined]
    return _counter._n  # type: ignore[attr-defined]


@pytest.fixture
def mock_executor() -> MagicMock:
    return MagicMock(spec=OrderExecutor)


@pytest.fixture
def mock_lifecycle() -> MagicMock:
    return MagicMock(spec=OrderLifecycleManager)


@pytest.fixture
def mock_reconciler() -> MagicMock:
    return MagicMock(spec=Reconciler)


@pytest.fixture
def mock_price_fetcher() -> MagicMock:
    from chimuelo_prime.grid_engine.price_fetcher import PriceFetcher

    pf = MagicMock(spec=PriceFetcher)
    pf.get_current_price.return_value = Decimal("120.00")
    return pf


@pytest.fixture
def engine(
    symbol_config: object,
    mock_grid_state: MagicMock,
    mock_executor: MagicMock,
    mock_lifecycle: MagicMock,
    mock_reconciler: MagicMock,
    mock_price_fetcher: MagicMock,
) -> GridEngine:
    from chimuelo_prime.exchange_config.models import SymbolConfig

    assert isinstance(symbol_config, SymbolConfig)
    return GridEngine(
        config=symbol_config,
        grid_state=mock_grid_state,
        executor=mock_executor,
        lifecycle=mock_lifecycle,
        reconciler=mock_reconciler,
        price_fetcher=mock_price_fetcher,
        poll_interval=0.0,
    )


# ---------------------------------------------------------------------------
# Caso 7 & 8: _setup enruta correctamente
# ---------------------------------------------------------------------------
class TestSetup:
    def test_routes_to_initialize_when_no_existing_levels(
        self, engine: GridEngine, mock_grid_state: MagicMock, mock_price_fetcher: MagicMock
    ) -> None:
        mock_grid_state.get_grid_levels.return_value = []
        mock_grid_state.save_grid_level.side_effect = iter(range(1, 100))
        mock_executor = engine._executor
        mock_executor.place_limit_buy.return_value = _make_placed_order(1)

        engine._setup()

        # save_grid_level fue llamado → se ejecutó _initialize_new_grid
        mock_grid_state.save_grid_level.assert_called()
        # reconciler NO fue llamado
        engine._reconciler.reconcile.assert_not_called()

    def test_routes_to_resume_when_levels_exist(
        self, engine: GridEngine, mock_grid_state: MagicMock
    ) -> None:
        existing = [_make_grid_level(1)]
        mock_grid_state.get_grid_levels.return_value = existing
        mock_grid_state.get_order.return_value = None

        engine._setup()

        engine._reconciler.reconcile.assert_called_once_with("SOLUSDT")
        # save_grid_level NO fue llamado
        mock_grid_state.save_grid_level.assert_not_called()


# ---------------------------------------------------------------------------
# Casos 9-13: _initialize_new_grid
# ---------------------------------------------------------------------------
class TestInitializeNewGrid:
    def test_saves_all_level_specs_as_grid_levels(
        self, engine: GridEngine, mock_grid_state: MagicMock, symbol_config: object
    ) -> None:
        from chimuelo_prime.exchange_config.models import SymbolConfig

        assert isinstance(symbol_config, SymbolConfig)
        saved_ids = iter(range(1, 1000))
        mock_grid_state.save_grid_level.side_effect = lambda _: next(saved_ids)
        engine._executor.place_limit_buy.return_value = _make_placed_order(99)

        engine._initialize_new_grid()

        assert mock_grid_state.save_grid_level.call_count == symbol_config.grid_levels

    def test_places_buy_for_levels_below_current_price(
        self, engine: GridEngine, mock_grid_state: MagicMock, mock_price_fetcher: MagicMock
    ) -> None:
        # price = 120.00; rango 100-140, 20 niveles → spacing = 2.0
        # niveles con lower_price < 120 son niveles 0..9 (10 niveles)
        mock_price_fetcher.get_current_price.return_value = Decimal("120.00")
        saved_ids = iter(range(1, 1000))
        mock_grid_state.save_grid_level.side_effect = lambda _: next(saved_ids)

        placed_calls: list[MagicMock] = []

        def capture_buy(**kwargs: object) -> PlacedOrder:
            placed_calls.append(MagicMock())
            return _make_placed_order(len(placed_calls))

        engine._executor.place_limit_buy.side_effect = capture_buy

        engine._initialize_new_grid()

        # Con precio en 120 y rango 100-140 en 20 niveles (spacing=2),
        # los niveles 0..9 tienen lower_price en 100..118 < 120 → 10 BUYs
        assert engine._executor.place_limit_buy.call_count == 10

    def test_no_buy_placed_for_levels_at_or_above_current_price(
        self, engine: GridEngine, mock_grid_state: MagicMock, mock_price_fetcher: MagicMock
    ) -> None:
        # price = 100.00 = lower_bound → ningún nivel está estrictamente por debajo
        mock_price_fetcher.get_current_price.return_value = Decimal("100.00")
        saved_ids = iter(range(1, 1000))
        mock_grid_state.save_grid_level.side_effect = lambda _: next(saved_ids)

        engine._initialize_new_grid()

        engine._executor.place_limit_buy.assert_not_called()

    def test_grid_calculation_error_propagates(
        self, engine: GridEngine, mock_grid_state: MagicMock
    ) -> None:
        saved_ids = iter(range(1, 1000))
        mock_grid_state.save_grid_level.side_effect = lambda _: next(saved_ids)

        with (
            patch(
                "chimuelo_prime.grid_engine.engine.GridCalculator.compute_levels",
                side_effect=GridCalculationError("capital insuficiente"),
            ),
            pytest.raises(GridCalculationError),
        ):
            engine._initialize_new_grid()

    def test_price_fetch_error_propagates(
        self, engine: GridEngine, mock_price_fetcher: MagicMock
    ) -> None:
        mock_price_fetcher.get_current_price.side_effect = PriceFetchError("endpoint caído")

        with pytest.raises(PriceFetchError):
            engine._initialize_new_grid()


# ---------------------------------------------------------------------------
# Casos 14-17: _resume_existing_grid
# ---------------------------------------------------------------------------
class TestResumeExistingGrid:
    def test_calls_reconciler_reconcile(
        self, engine: GridEngine, mock_grid_state: MagicMock
    ) -> None:
        levels = [_make_grid_level(1)]
        mock_grid_state.get_order.return_value = None

        engine._resume_existing_grid(levels)

        engine._reconciler.reconcile.assert_called_once_with("SOLUSDT")

    def test_places_sell_for_filled_buy_without_sell(
        self, engine: GridEngine, mock_grid_state: MagicMock
    ) -> None:
        level = _make_grid_level(1, buy_order_id=101, sell_order_id=None)

        filled_order = MagicMock()
        filled_order.status = OrderStatus.FILLED.value
        filled_order.qty = Decimal("0.10")

        mock_grid_state.get_order.return_value = filled_order
        engine._executor.place_limit_sell.return_value = _make_placed_order(202, side="SELL")

        engine._resume_existing_grid([level])

        engine._executor.place_limit_sell.assert_called_once()
        call_kwargs = engine._executor.place_limit_sell.call_args.kwargs
        assert call_kwargs["level_id"] == 1
        assert call_kwargs["price"] == level.upper_price
        assert call_kwargs["qty"] == Decimal("0.10")

    def test_no_sell_placed_when_sell_already_exists(
        self, engine: GridEngine, mock_grid_state: MagicMock
    ) -> None:
        level = _make_grid_level(1, buy_order_id=101, sell_order_id=202)
        mock_grid_state.get_order.return_value = None

        engine._resume_existing_grid([level])

        engine._executor.place_limit_sell.assert_not_called()

    def test_no_sell_placed_when_buy_not_filled(
        self, engine: GridEngine, mock_grid_state: MagicMock
    ) -> None:
        level = _make_grid_level(1, buy_order_id=101, sell_order_id=None)

        open_order = MagicMock()
        open_order.status = OrderStatus.NEW.value

        mock_grid_state.get_order.return_value = open_order

        engine._resume_existing_grid([level])

        engine._executor.place_limit_sell.assert_not_called()


# ---------------------------------------------------------------------------
# Casos 18-21: _run_poll_cycle
# ---------------------------------------------------------------------------
class TestRunPollCycle:
    def test_syncs_each_open_order(
        self, engine: GridEngine, mock_grid_state: MagicMock, mock_lifecycle: MagicMock
    ) -> None:
        orders = [_make_open_order(1), _make_open_order(2), _make_open_order(3)]
        mock_grid_state.get_open_orders.return_value = orders
        mock_lifecycle.sync_order_status.return_value = _make_status_update(
            1, OrderStatus.NEW, OrderStatus.NEW, status_changed=False
        )

        engine._run_poll_cycle()

        assert mock_lifecycle.sync_order_status.call_count == 3

    def test_collect_and_continue_on_sync_error(
        self, engine: GridEngine, mock_grid_state: MagicMock, mock_lifecycle: MagicMock
    ) -> None:
        orders = [_make_open_order(1), _make_open_order(2), _make_open_order(3)]
        mock_grid_state.get_open_orders.return_value = orders

        # La orden 2 falla; las demás deben sincronizarse igual
        mock_lifecycle.sync_order_status.side_effect = [
            _make_status_update(1, OrderStatus.NEW, OrderStatus.NEW, status_changed=False),
            StatusSyncError("timeout"),
            _make_status_update(3, OrderStatus.NEW, OrderStatus.NEW, status_changed=False),
        ]

        # No debe lanzar excepción
        engine._run_poll_cycle()

        # Los tres intentos se hicieron
        assert mock_lifecycle.sync_order_status.call_count == 3

    def test_calls_on_buy_filled_when_buy_transitions(
        self, engine: GridEngine, mock_grid_state: MagicMock, mock_lifecycle: MagicMock
    ) -> None:
        buy_order = _make_open_order(order_id=50, side="BUY")
        mock_grid_state.get_open_orders.return_value = [buy_order]

        update = _make_status_update(
            50, OrderStatus.NEW, OrderStatus.FILLED, executed_qty=Decimal("0.10")
        )
        mock_lifecycle.sync_order_status.return_value = update

        # Registrar el nivel en el índice del engine
        engine._buy_order_to_level[50] = 1
        level = _make_grid_level(1)
        mock_grid_state.get_grid_level.return_value = level
        engine._executor.place_limit_sell.return_value = _make_placed_order(99, side="SELL")

        engine._run_poll_cycle()

        engine._executor.place_limit_sell.assert_called_once()

    def test_calls_on_sell_filled_when_sell_transitions(
        self, engine: GridEngine, mock_grid_state: MagicMock, mock_lifecycle: MagicMock
    ) -> None:
        sell_order = _make_open_order(order_id=60, side="SELL")
        mock_grid_state.get_open_orders.return_value = [sell_order]

        update = _make_status_update(60, OrderStatus.NEW, OrderStatus.FILLED)
        mock_lifecycle.sync_order_status.return_value = update

        # Para que _on_sell_filled → _take_snapshot no falle
        mock_grid_state.get_open_orders.side_effect = [
            [sell_order],  # primer get_open_orders en _run_poll_cycle
            [],  # segundo en _take_snapshot
        ]

        engine._run_poll_cycle()

        mock_grid_state.save_snapshot.assert_called_once()


# ---------------------------------------------------------------------------
# Casos 22-23: _on_buy_filled
# ---------------------------------------------------------------------------
class TestOnBuyFilled:
    def _setup_level(
        self,
        engine: GridEngine,
        mock_grid_state: MagicMock,
        buy_order_id: int,
        level_id: int,
        upper_price: Decimal,
    ) -> None:
        engine._buy_order_to_level[buy_order_id] = level_id
        level = _make_grid_level(level_id, buy_order_id=buy_order_id)
        level.upper_price = upper_price
        mock_grid_state.get_grid_level.return_value = level
        engine._executor.place_limit_sell.return_value = _make_placed_order(999, side="SELL")

    def test_places_sell_at_upper_price(
        self, engine: GridEngine, mock_grid_state: MagicMock
    ) -> None:
        upper = Decimal("102.00")
        self._setup_level(engine, mock_grid_state, buy_order_id=10, level_id=1, upper_price=upper)

        engine._on_buy_filled(buy_order_id=10, executed_qty=Decimal("0.10"))

        call_kwargs = engine._executor.place_limit_sell.call_args.kwargs
        assert call_kwargs["price"] == upper

    def test_places_sell_with_executed_qty(
        self, engine: GridEngine, mock_grid_state: MagicMock
    ) -> None:
        self._setup_level(
            engine, mock_grid_state, buy_order_id=10, level_id=1, upper_price=Decimal("102.00")
        )
        qty = Decimal("0.15")

        engine._on_buy_filled(buy_order_id=10, executed_qty=qty)

        call_kwargs = engine._executor.place_limit_sell.call_args.kwargs
        assert call_kwargs["qty"] == qty


# ---------------------------------------------------------------------------
# Caso 24: _on_sell_filled
# ---------------------------------------------------------------------------
class TestOnSellFilled:
    def test_takes_snapshot_on_sell_fill(
        self, engine: GridEngine, mock_grid_state: MagicMock
    ) -> None:
        mock_grid_state.get_open_orders.return_value = []

        engine._on_sell_filled(sell_order_id=99)

        mock_grid_state.save_snapshot.assert_called_once()


# ---------------------------------------------------------------------------
# Caso 25: _take_snapshot
# ---------------------------------------------------------------------------
class TestTakeSnapshot:
    def test_save_snapshot_called_with_snapshot_instance(
        self, engine: GridEngine, mock_grid_state: MagicMock
    ) -> None:
        mock_grid_state.get_open_orders.return_value = []

        engine._take_snapshot()

        mock_grid_state.save_snapshot.assert_called_once()
        args = mock_grid_state.save_snapshot.call_args[0]
        assert isinstance(args[0], Snapshot)

    def test_equity_equals_sum_of_buy_order_notionals(
        self, engine: GridEngine, mock_grid_state: MagicMock
    ) -> None:
        buy1 = _make_open_order(1, side="BUY")
        buy1.price = Decimal("100.00")
        buy1.qty = Decimal("0.10")

        buy2 = _make_open_order(2, side="BUY")
        buy2.price = Decimal("102.00")
        buy2.qty = Decimal("0.10")

        mock_grid_state.get_open_orders.return_value = [buy1, buy2]

        engine._take_snapshot()

        saved_snapshot: Snapshot = mock_grid_state.save_snapshot.call_args[0][0]
        expected_cash = Decimal("100.00") * Decimal("0.10") + Decimal("102.00") * Decimal("0.10")
        assert saved_snapshot.cash == expected_cash
        assert saved_snapshot.equity == expected_cash


# ---------------------------------------------------------------------------
# Caso 26: stop()
# ---------------------------------------------------------------------------
class TestStop:
    def test_stop_sets_threading_event(self, engine: GridEngine) -> None:
        assert not engine._stop_event.is_set()
        engine.stop()
        assert engine._stop_event.is_set()


# ---------------------------------------------------------------------------
# Casos 27-29: _shutdown
# ---------------------------------------------------------------------------
class TestShutdown:
    def test_calls_cancel_all_open_orders(
        self, engine: GridEngine, mock_executor: MagicMock, mock_grid_state: MagicMock
    ) -> None:
        mock_executor.cancel_all_open_orders.return_value = []
        mock_grid_state.get_open_orders.return_value = []

        engine._shutdown()

        mock_executor.cancel_all_open_orders.assert_called_once_with("SOLUSDT")

    def test_does_not_reraise_aggregate_cancellation_error(
        self, engine: GridEngine, mock_executor: MagicMock, mock_grid_state: MagicMock
    ) -> None:
        mock_executor.cancel_all_open_orders.side_effect = AggregateCancellationError(
            "2 cancelaciones fallaron",
            partial_results=[],
            errors=[(1, Exception("timeout")), (2, Exception("timeout"))],
        )
        mock_grid_state.get_open_orders.return_value = []

        # No debe propagar AggregateCancellationError
        engine._shutdown()

        mock_grid_state.save_snapshot.assert_called_once()

    def test_takes_snapshot_even_if_cancel_fails(
        self, engine: GridEngine, mock_executor: MagicMock, mock_grid_state: MagicMock
    ) -> None:
        mock_executor.cancel_all_open_orders.side_effect = AggregateCancellationError(
            "fallo",
            partial_results=[],
            errors=[(1, RuntimeError("x"))],
        )
        mock_grid_state.get_open_orders.return_value = []

        engine._shutdown()

        mock_grid_state.save_snapshot.assert_called_once()

    def test_handles_non_aggregate_exception_from_cancel(
        self, engine: GridEngine, mock_executor: MagicMock, mock_grid_state: MagicMock
    ) -> None:
        mock_executor.cancel_all_open_orders.side_effect = RuntimeError("connection refused")
        mock_grid_state.get_open_orders.return_value = []

        engine._shutdown()  # no debe propagar RuntimeError

        mock_grid_state.save_snapshot.assert_called_once()


# ---------------------------------------------------------------------------
# start() — cubre líneas 90-91 y el bucle _run() (líneas 221-228)
# ---------------------------------------------------------------------------
class TestStartAndRun:
    def test_start_calls_setup_then_run(
        self,
        engine: GridEngine,
        mock_grid_state: MagicMock,
        mock_executor: MagicMock,
        mock_price_fetcher: MagicMock,
    ) -> None:
        # Sin niveles existentes → _initialize_new_grid
        mock_grid_state.get_grid_levels.return_value = []
        saved_ids = iter(range(1, 1000))
        mock_grid_state.save_grid_level.side_effect = lambda _: next(saved_ids)
        mock_price_fetcher.get_current_price.return_value = Decimal("100.00")
        mock_executor.cancel_all_open_orders.return_value = []
        mock_grid_state.get_open_orders.return_value = []

        # Detener el bucle inmediatamente para que start() no bloquee
        engine.stop()

        engine.start()

        mock_grid_state.get_grid_levels.assert_called()
        mock_grid_state.save_snapshot.assert_called()  # _shutdown → _take_snapshot

    def test_run_continues_after_unexpected_poll_exception(
        self, engine: GridEngine, mock_executor: MagicMock, mock_grid_state: MagicMock
    ) -> None:
        """El except genérico en _run() no re-lanza — el bucle sigue."""
        call_count = 0

        def poll_then_stop() -> None:
            nonlocal call_count
            call_count += 1
            engine.stop()
            raise RuntimeError("error inesperado en ciclo")

        engine._run_poll_cycle = poll_then_stop  # type: ignore[method-assign]
        mock_executor.cancel_all_open_orders.return_value = []
        mock_grid_state.get_open_orders.return_value = []

        engine._run()  # no debe propagar RuntimeError

        assert call_count == 1
        mock_grid_state.save_snapshot.assert_called()  # _shutdown ejecutado


# ---------------------------------------------------------------------------
# Ramas defensivas de _place_missing_sells y _on_buy_filled
# ---------------------------------------------------------------------------
class TestDefensivePaths:
    def test_place_missing_sells_skips_when_buy_order_disappears(
        self, engine: GridEngine, mock_grid_state: MagicMock
    ) -> None:
        """Race condition: la orden estaba FILLED en find, desapareció en place."""
        level = _make_grid_level(1, buy_order_id=101, sell_order_id=None)

        filled = MagicMock()
        filled.status = OrderStatus.FILLED.value

        # 1ª llamada: _find_levels_missing_sell (retorna filled → level entra en missing)
        # 2ª llamada: _place_missing_sells (retorna None → skip)
        mock_grid_state.get_order.side_effect = [filled, None]

        engine._place_missing_sells([level])

        engine._executor.place_limit_sell.assert_not_called()

    def test_place_missing_sells_handles_sell_placement_failure(
        self, engine: GridEngine, mock_grid_state: MagicMock
    ) -> None:
        """Si place_limit_sell lanza, _place_missing_sells lo captura y sigue."""
        level = _make_grid_level(1, buy_order_id=101, sell_order_id=None)

        filled = MagicMock()
        filled.status = OrderStatus.FILLED.value
        filled.qty = Decimal("0.10")

        mock_grid_state.get_order.return_value = filled
        engine._executor.place_limit_sell.side_effect = RuntimeError("Binance down")

        engine._place_missing_sells([level])  # no debe propagar

    def test_on_buy_filled_handles_unmapped_order_id(self, engine: GridEngine) -> None:
        """buy_order_id no registrado en _buy_order_to_level → early return."""
        engine._on_buy_filled(buy_order_id=9999, executed_qty=Decimal("0.10"))

        engine._executor.place_limit_sell.assert_not_called()

    def test_on_buy_filled_handles_missing_level_in_db(
        self, engine: GridEngine, mock_grid_state: MagicMock
    ) -> None:
        """level_id mapeado pero GridLevel ya no existe en M3 → early return."""
        engine._buy_order_to_level[50] = 1
        mock_grid_state.get_grid_level.return_value = None

        engine._on_buy_filled(buy_order_id=50, executed_qty=Decimal("0.10"))

        engine._executor.place_limit_sell.assert_not_called()

    def test_on_buy_filled_handles_sell_placement_failure(
        self, engine: GridEngine, mock_grid_state: MagicMock
    ) -> None:
        """place_limit_sell lanza → _on_buy_filled lo captura (critical log)."""
        engine._buy_order_to_level[50] = 1
        level = _make_grid_level(1)
        mock_grid_state.get_grid_level.return_value = level
        engine._executor.place_limit_sell.side_effect = RuntimeError("network error")

        engine._on_buy_filled(buy_order_id=50, executed_qty=Decimal("0.10"))  # no propaga

    def test_on_order_expired_does_not_raise(self, engine: GridEngine) -> None:
        """_on_order_expired es solo logging en v1."""
        engine._on_order_expired(order_id=1)  # no debe lanzar
