"""Orquestador multi-activo y multi-hilo para Chimuelo Prime (M7).

Responsabilidades:
    1. Validar credenciales de Binance en variables de entorno.
    2. Sincronizar automáticamente el desfase del reloj local con el servidor de Binance.
    3. Inicializar el motor SQLite en WAL mode y persistir/reconciliar estados.
    4. Instanciar y coordinar la ejecución del bucle GridEngine de cada par en hilos independientes.
    5. Escuchar y despachar señales de apagado graceful (SIGINT, SIGTERM) liberando
       todas las conexiones del pool de bases de datos.
"""

from __future__ import annotations

import signal
import threading
from types import FrameType
from typing import Any

from chimuelo_prime.api_client.client import BinanceAuthenticatedClient
from chimuelo_prime.api_client.models import BinanceCredentials
from chimuelo_prime.api_client.rate_limiter import RateLimiter
from chimuelo_prime.api_client.signing import BinanceSigner
from chimuelo_prime.exchange_config.client import BinancePublicClient
from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.exchange_config.models import SymbolConfig
from chimuelo_prime.exchange_config.service import ExchangeConfigService
from chimuelo_prime.grid_engine.engine import GridEngine
from chimuelo_prime.grid_engine.price_fetcher import PriceFetcher
from chimuelo_prime.grid_state.database import build_engine
from chimuelo_prime.grid_state.grid_state import GridState
from chimuelo_prime.grid_state.reconciler import Reconciler
from chimuelo_prime.orchestrator.config_manager import OrchestratorConfig
from chimuelo_prime.orchestrator.monitoring import AlertManager
from chimuelo_prime.order_execution.executor import OrderExecutor
from chimuelo_prime.order_execution.lifecycle import OrderLifecycleManager


class Orchestrator:
    """Coordinador central del ciclo de vida multi-hilo de Chimuelo Prime.

    Gestiona la inicialización de recursos comunes y la orquestación segura
    de instancias GridEngine individuales por cada símbolo activo configurado.
    """

    def __init__(self, config: OrchestratorConfig, db_url: str = "sqlite:///chimuelo.db") -> None:
        self.config = config
        self.db_url = db_url
        self.alert_manager = AlertManager()
        self._log = get_logger(__name__)

        self._db_engine: Any | None = None
        self._grid_state: GridState | None = None
        self._public_client: BinancePublicClient | None = None
        self._authenticated_client: BinanceAuthenticatedClient | None = None

        self._engines: dict[str, GridEngine] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stop_event = threading.Event()
        self._is_running = False

    def setup(self) -> None:
        """Inicializa conexiones de bases de datos, clientes de red y motores."""
        self._log.info("orchestrator.setup.start")

        # 1. Cargar y validar credenciales de Binance
        credentials = BinanceCredentials.from_env()

        # 2. Inicializar DB SQLite y servicio de persistencia (WAL mode)
        self._db_engine = build_engine(self.db_url)
        self._grid_state = GridState(self._db_engine)

        # 3. Inicializar clientes de red
        active_env = self.config.active_env
        self._public_client = BinancePublicClient(
            base_url=active_env.base_url,
            timeout=active_env.http_timeout_seconds,
        )

        # Sincronización del desfase de reloj (prevent -1021)
        try:
            first_symbol = self.config.symbols[0]
            raw_info = self._public_client.get_exchange_info(first_symbol)
            server_time_ms = raw_info.get("serverTime")
            if not server_time_ms:
                raise ValueError("serverTime ausente en exchangeInfo")
        except Exception as exc:
            self._log.error("orchestrator.time_sync_failed", error=str(exc))
            self.alert_manager.trigger_alert(
                "TIME_SYNC_FAILED",
                f"No se pudo sincronizar el tiempo del servidor Binance: {exc}",
            )
            raise

        signer = BinanceSigner(
            credentials=credentials,
        )
        rate_limiter = RateLimiter(self.config.api_client.rate_limit)

        self._authenticated_client = BinanceAuthenticatedClient(
            base_url=active_env.base_url,
            signer=signer,
            rate_limiter=rate_limiter,
            retry_config=self.config.api_client.retry,
            timeout=active_env.http_timeout_seconds,
        )
        # Sincronizar el reloj del cliente autenticado
        self._authenticated_client.sync_server_time(server_time_ms)

        # 4. Inicializar componentes y servicios comunes
        config_service = ExchangeConfigService(self._public_client)
        reconciler = Reconciler(self._grid_state, self._authenticated_client)
        price_fetcher = PriceFetcher(self._public_client)

        # 5. Configurar cada motor GridEngine por par de trading
        for symbol in self.config.symbols:
            self._log.info("orchestrator.setup.symbol", symbol=symbol)

            # Obtener y parsear filtros
            filters = config_service.fetch_symbol_filters(symbol)

            # Obtener estrategia
            strategy = self.config.strategies[symbol]
            symbol_config = SymbolConfig(
                filters=filters,
                upper_bound=strategy.upper_bound,
                lower_bound=strategy.lower_bound,
                grid_levels=strategy.grid_levels,
                capital_per_order=strategy.capital_per_order,
                capital_weight=strategy.capital_weight,
            )

            # Instanciar el ejecutor de órdenes y manager de ciclo de vida (M4)
            executor = OrderExecutor(
                client=self._authenticated_client,
                grid_state=self._grid_state,
                config=symbol_config,
            )
            lifecycle = OrderLifecycleManager(
                client=self._authenticated_client,
                grid_state=self._grid_state,
            )

            # Reconciliación offline preventiva al arrancar (M3-01)
            try:
                reconciler.reconcile(symbol)
            except Exception as exc:
                self._log.error("orchestrator.reconciliation_failed", symbol=symbol, error=str(exc))
                self.alert_manager.trigger_alert(
                    "RECONCILIATION_FAILED",
                    f"Reconciliación inicial fallida para {symbol}: {exc}",
                    symbol=symbol,
                )
                raise

            # Crear motor GridEngine
            engine = GridEngine(
                config=symbol_config,
                grid_state=self._grid_state,
                executor=executor,
                lifecycle=lifecycle,
                reconciler=reconciler,
                price_fetcher=price_fetcher,
                alert_manager=self.alert_manager,
            )
            self._engines[symbol] = engine

        self._log.info("orchestrator.setup.complete")

    def start(self) -> None:
        """Arranca el orquestador lanzando cada GridEngine en su propio hilo."""
        if self._is_running:
            self._log.warning("orchestrator.already_running")
            return

        self.setup()
        self._is_running = True
        self._stop_event.clear()

        # Configurar manejadores de señales para apagado graceful
        try:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
        except ValueError:
            # Captura fallos de registro de señal en subhilos (ej. entornos de test)
            pass

        # Iniciar hilos individuales
        for symbol, engine in self._engines.items():
            self._log.info("orchestrator.start_thread", symbol=symbol)
            thread = threading.Thread(
                target=engine.start,
                name=f"GridEngine-{symbol}",
                daemon=True,
            )
            thread.start()
            self._threads[symbol] = thread

        # Bloquear hilo principal esperando apagado
        while not self._stop_event.is_set():
            try:
                self._stop_event.wait(1.0)
            except KeyboardInterrupt:
                self._log.info("orchestrator.keyboard_interrupt")
                break

        self.stop()

    def stop(self) -> None:
        """Detiene ordenadamente todos los GridEngines y libera recursos."""
        if not self._is_running:
            return

        self._log.info("orchestrator.stop.start")
        self._stop_event.set()

        # 1. Señalar terminación a cada motor
        for symbol, engine in self._engines.items():
            self._log.info("orchestrator.stopping_engine", symbol=symbol)
            try:
                engine.stop()
            except Exception as exc:
                self._log.error("orchestrator.stop_engine_failed", symbol=symbol, error=str(exc))

        # 2. Esperar a que terminen los hilos (limpieza final en bucles)
        for symbol, thread in self._threads.items():
            self._log.info("orchestrator.joining_thread", symbol=symbol)
            thread.join(timeout=15.0)
            if thread.is_alive():
                self._log.warning("orchestrator.thread_hung", symbol=symbol)

        # 3. Cerrar sesiones HTTP de clientes
        if self._authenticated_client:
            self._log.info("orchestrator.closing_authenticated_client")
            try:
                self._authenticated_client.close()
            except Exception as exc:
                self._log.error("orchestrator.close_auth_client_failed", error=str(exc))

        if self._public_client:
            self._log.info("orchestrator.closing_public_client")
            try:
                self._public_client.close()
            except Exception as exc:
                self._log.error("orchestrator.close_public_client_failed", error=str(exc))

        # 4. Cerrar el pool de base de datos SQLite para evitar leaks y warnings
        if self._db_engine:
            self._log.info("orchestrator.disposing_db_engine")
            try:
                self._db_engine.dispose()
            except Exception as exc:
                self._log.error("orchestrator.db_dispose_failed", error=str(exc))

        self._is_running = False
        self._log.info("orchestrator.stop.complete")

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        """Intercepta señales de interrupción del sistema para iniciar apagado."""
        self._log.warning("orchestrator.signal_received", signum=signum)
        self._stop_event.set()
