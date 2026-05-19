"""Orquestador principal del grid trading (M5).

GridEngine coordina todos los módulos del sistema:
    - M1 (exchange_config): filtros y configuración del símbolo.
    - M3 (grid_state): persistencia transaccional + reconciliación.
    - M4 (order_execution): colocación y cancelación de órdenes.
    - M5 (calculator, price_fetcher): geometría y precio spot.

Ciclo de vida:
    1. start() → _setup() → _initialize_new_grid() o _resume_existing_grid()
    2. _run() → bucle de polling cada poll_interval segundos
    3. stop() → señala fin del bucle → _shutdown()

Garantías:
    - Cero floats en cálculos financieros.
    - collect-and-continue en _run_poll_cycle: un fallo no detiene el ciclo.
    - _shutdown no re-lanza AggregateCancellationError: intenta cancelar todo.
    - Flaw 1 mitigado: _resume_existing_grid detecta BUYs FILLED sin SELL.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from decimal import Decimal

from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.exchange_config.models import SymbolConfig
from chimuelo_prime.grid_engine.calculator import GridCalculator
from chimuelo_prime.grid_engine.price_fetcher import PriceFetcher
from chimuelo_prime.grid_state.grid_state import GridState
from chimuelo_prime.grid_state.reconciler import Reconciler
from chimuelo_prime.grid_state.schema import GridLevel, OrderStatus, Snapshot
from chimuelo_prime.order_execution.exceptions import AggregateCancellationError
from chimuelo_prime.order_execution.executor import OrderExecutor
from chimuelo_prime.order_execution.lifecycle import OrderLifecycleManager


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class GridEngine:
    """Orquestador del ciclo de vida del grid de trading.

    Todas las dependencias se inyectan — nunca se instancian internamente.
    Un único SymbolConfig por instancia: para operar múltiples símbolos,
    se crea una instancia por símbolo.

    Args:
        config:        Configuración del símbolo (filtros + parámetros de estrategia).
        grid_state:    Servicio de persistencia de M3.
        executor:      Servicio de colocación/cancelación de M4.
        lifecycle:     Servicio de sincronización de estado de M4.
        reconciler:    Reconciliador de estado de M3.
        price_fetcher: Obtenedor de precio spot de M5.
        poll_interval: Segundos entre ciclos de polling (default: 30).
    """

    def __init__(
        self,
        config: SymbolConfig,
        grid_state: GridState,
        executor: OrderExecutor,
        lifecycle: OrderLifecycleManager,
        reconciler: Reconciler,
        price_fetcher: PriceFetcher,
        poll_interval: float = 30.0,
    ) -> None:
        self._config = config
        self._symbol = config.filters.symbol
        self._grid_state = grid_state
        self._executor = executor
        self._lifecycle = lifecycle
        self._reconciler = reconciler
        self._price_fetcher = price_fetcher
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._log = get_logger(__name__)

        # Routing en memoria: order_id → level_id (se reconstruye al resumir)
        self._buy_order_to_level: dict[int, int] = {}
        self._sell_order_to_level: dict[int, int] = {}

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Inicializa el grid y lanza el bucle de polling (bloqueante)."""
        self._setup()
        self._run()

    def stop(self) -> None:
        """Señala al bucle principal que termine tras el ciclo en curso."""
        self._log.info("engine.stopping", symbol=self._symbol)
        self._stop_event.set()

    # ------------------------------------------------------------------ #
    # Inicialización
    # ------------------------------------------------------------------ #
    def _setup(self) -> None:
        """Decide entre grid nuevo y reanudación según el estado en M3."""
        existing = self._grid_state.get_grid_levels(self._symbol)
        if existing:
            self._resume_existing_grid(existing)
        else:
            self._initialize_new_grid()

    def _initialize_new_grid(self) -> None:
        """Grid nuevo: calcula niveles, los persiste y coloca los BUYs iniciales.

        Raises:
            PriceFetchError:       si no se puede obtener el precio spot.
            GridCalculationError:  si la config produce niveles inválidos.
            OrderPlacementError:   si Binance rechaza alguna orden inicial.
        """
        current_price = self._price_fetcher.get_current_price(self._symbol)
        level_specs = GridCalculator.compute_levels(self._config)

        # Persistir todos los niveles antes de colocar cualquier orden
        level_ids: list[int] = []
        for spec in level_specs:
            gl = GridLevel(
                symbol=self._symbol,
                lower_price=spec.lower_price,
                upper_price=spec.upper_price,
                created_at=_utcnow(),
            )
            level_id = self._grid_state.save_grid_level(gl)
            level_ids.append(level_id)

        # Colocar BUY solo para niveles estrictamente por debajo del precio actual
        below = GridCalculator.levels_below_price(level_specs, current_price)
        below_indices = {spec.level_index for spec in below}

        for spec, lid in zip(level_specs, level_ids):
            if spec.level_index not in below_indices:
                continue
            placed = self._executor.place_limit_buy(
                price=spec.lower_price,
                qty=spec.qty,
                level_id=lid,
            )
            self._buy_order_to_level[placed.order_id] = lid
            self._log.info(
                "engine.buy_placed",
                level_id=lid,
                order_id=placed.order_id,
                price=str(spec.lower_price),
            )

    def _resume_existing_grid(self, existing_levels: list[GridLevel]) -> None:
        """Reanuda el grid: reconcilia con Binance y repara SELLs faltantes.

        Args:
            existing_levels: Niveles persistidos en M3 al arrancar.

        Raises:
            ReconciliationError: si Binance retorna error durante la reconciliación.
        """
        self._reconciler.reconcile(self._symbol)

        # Reconstruir índices en memoria desde el estado persistido
        for level in existing_levels:
            if level.buy_order_id is not None:
                self._buy_order_to_level[level.buy_order_id] = level.level_id
            if level.sell_order_id is not None:
                self._sell_order_to_level[level.sell_order_id] = level.level_id

        self._place_missing_sells(existing_levels)

    def _find_levels_missing_sell(self, levels: list[GridLevel]) -> list[GridLevel]:
        """Retorna niveles donde el BUY está FILLED pero el SELL nunca se colocó.

        Flaw 1: si el bot se cayó después de que Binance ejecutó el BUY pero
        antes de que M5 colocara el SELL, la ganancia nunca se materializará
        a menos que se detecte y repare en el próximo arranque.
        """
        result: list[GridLevel] = []
        for level in levels:
            if level.sell_order_id is not None:
                continue
            if level.buy_order_id is None:
                continue
            order = self._grid_state.get_order(level.buy_order_id)
            if order is not None and order.status == OrderStatus.FILLED.value:
                result.append(level)
        return result

    def _place_missing_sells(self, levels: list[GridLevel]) -> None:
        """Coloca los SELLs que no se colocaron antes del crash."""
        missing = self._find_levels_missing_sell(levels)
        for level in missing:
            buy_order = self._grid_state.get_order(level.buy_order_id)  # type: ignore[arg-type]
            if buy_order is None:
                continue
            try:
                placed = self._executor.place_limit_sell(
                    price=level.upper_price,
                    qty=buy_order.qty,
                    level_id=level.level_id,
                )
                self._sell_order_to_level[placed.order_id] = level.level_id
                self._log.warning(
                    "engine.missing_sell_placed",
                    level_id=level.level_id,
                    sell_order_id=placed.order_id,
                )
            except Exception as exc:
                self._log.critical(
                    "engine.missing_sell_placement_failed",
                    level_id=level.level_id,
                    error=str(exc),
                )

    # ------------------------------------------------------------------ #
    # Bucle de polling
    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        """Bucle principal: polling hasta que stop() señale el evento."""
        self._log.info("engine.running", symbol=self._symbol)
        while not self._stop_event.is_set():
            try:
                self._run_poll_cycle()
            except Exception as exc:
                self._log.error("engine.poll_error", symbol=self._symbol, error=str(exc))
            self._stop_event.wait(self._poll_interval)
        self._shutdown()

    def _run_poll_cycle(self) -> None:
        """Sincroniza cada orden abierta. Collect-and-continue.

        Un error en sync_order_status para una orden no interrumpe la
        sincronización de las restantes. Los errores se loguean pero no
        se relanza nada: el próximo ciclo reintentará.
        """
        open_orders = self._grid_state.get_open_orders(self._symbol)
        errors: list[tuple[int, Exception]] = []

        for order in open_orders:
            try:
                update = self._lifecycle.sync_order_status(order.order_id, self._symbol)
                if update.status_changed and update.current_status == OrderStatus.FILLED:
                    if order.side == "BUY":
                        self._on_buy_filled(order.order_id, update.executed_qty)
                    elif order.side == "SELL":
                        self._on_sell_filled(order.order_id)
            except Exception as exc:
                self._log.error(
                    "engine.sync_failed",
                    order_id=order.order_id,
                    symbol=self._symbol,
                    error=str(exc),
                )
                errors.append((order.order_id, exc))

        if errors:
            self._log.warning(
                "engine.poll_cycle_partial_failure",
                symbol=self._symbol,
                failed_count=len(errors),
            )

    # ------------------------------------------------------------------ #
    # Callbacks de eventos de órdenes
    # ------------------------------------------------------------------ #
    def _on_buy_filled(self, buy_order_id: int, executed_qty: Decimal) -> None:
        """BUY ejecutado → colocar SELL complementario en upper_price del nivel."""
        level_id = self._buy_order_to_level.get(buy_order_id)
        if level_id is None:
            self._log.error("engine.buy_level_not_mapped", order_id=buy_order_id)
            return

        level = self._grid_state.get_grid_level(level_id)
        if level is None:
            self._log.error("engine.level_not_found", level_id=level_id)
            return

        try:
            placed = self._executor.place_limit_sell(
                price=level.upper_price,
                qty=executed_qty,
                level_id=level_id,
            )
            self._sell_order_to_level[placed.order_id] = level_id
            self._log.info(
                "engine.sell_placed_on_buy_fill",
                level_id=level_id,
                sell_order_id=placed.order_id,
                price=str(level.upper_price),
                qty=str(executed_qty),
            )
        except Exception as exc:
            self._log.critical(
                "engine.sell_placement_failed",
                level_id=level_id,
                buy_order_id=buy_order_id,
                error=str(exc),
            )

    def _on_sell_filled(self, sell_order_id: int) -> None:
        """SELL ejecutado → loguear ganancia y tomar snapshot."""
        level_id = self._sell_order_to_level.get(sell_order_id)
        self._log.info(
            "engine.sell_filled",
            sell_order_id=sell_order_id,
            level_id=level_id,
            symbol=self._symbol,
        )
        self._take_snapshot()

    def _on_order_expired(self, order_id: int) -> None:
        """Orden expirada → solo loguear en v1."""
        self._log.info("engine.order_expired", order_id=order_id, symbol=self._symbol)

    # ------------------------------------------------------------------ #
    # Snapshot y shutdown
    # ------------------------------------------------------------------ #
    def _take_snapshot(self) -> None:
        """Persiste una instantánea del portfolio en M3.

        v1: equity = capital comprometido en órdenes BUY abiertas.
        inventory y un P&L completo son scope de M7/backtester.
        """
        open_orders = self._grid_state.get_open_orders(self._symbol)
        cash = sum(
            (o.price * o.qty for o in open_orders if o.side == "BUY"),
            Decimal("0"),
        )
        inventory = Decimal("0")
        equity = cash + inventory

        snapshot = Snapshot(
            symbol=self._symbol,
            equity=equity,
            inventory=inventory,
            cash=cash,
            created_at=_utcnow(),
        )
        self._grid_state.save_snapshot(snapshot)
        self._log.debug("engine.snapshot_saved", symbol=self._symbol, equity=str(equity))

    def _shutdown(self) -> None:
        """Shutdown de emergencia: cancelar todas las órdenes y snapshot final.

        AggregateCancellationError se silencia a propósito: un shutdown de
        emergencia debe intentar cancelar todo aunque algunas fallen, y siempre
        tomar un snapshot final para preservar el estado del portfolio.
        """
        self._log.warning("engine.shutdown", symbol=self._symbol)
        try:
            self._executor.cancel_all_open_orders(self._symbol)
        except AggregateCancellationError as exc:
            self._log.error(
                "engine.shutdown_partial_cancel",
                symbol=self._symbol,
                failed=len(exc.errors),
                succeeded=len(exc.partial_results),
            )
        except Exception as exc:
            self._log.error("engine.shutdown_cancel_failed", error=str(exc))
        finally:
            self._take_snapshot()
