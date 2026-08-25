"""Servidor backend de FastAPI para el Dashboard Web de Chimuelo Prime (M8).

Proporciona endpoints REST y WebSocket para monitorear y controlar el
orquestador multi-activo en tiempo real de forma responsiva y fluida.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections import deque
from pathlib import Path as _Path


def _load_dotenv(env_file: _Path = _Path(".env")) -> None:
    """Carga variables de entorno desde .env sin dependencias externas.
    Solo asigna variables que aún no están definidas en el entorno del proceso.
    """
    if not env_file.exists():
        return
    with env_file.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from chimuelo_prime.api_client.client import BinanceAuthenticatedClient
from chimuelo_prime.backtesting.data_loader import HistoricalDataLoader
from chimuelo_prime.grid_state.schema import GridLevel, Order, Snapshot
from chimuelo_prime.orchestrator.config_manager import load_orchestrator_config
from chimuelo_prime.orchestrator.orchestrator import Orchestrator


# Configurar Logging Interceptor para WebSocket logs
class WebSocketLogHandler(logging.Handler):
    """Handler de logs para interceptar y almacenar mensajes recientes del bot."""

    def __init__(self, capacity: int = 200) -> None:
        super().__init__()
        self.log_queue: deque[str] = deque(maxlen=capacity)
        self.listeners: set[Any] = set()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.log_queue.append(msg)
            # Notificar listeners locales en segundo plano de forma segura
            for listener in list(self.listeners):
                with contextlib.suppress(Exception):
                    listener(msg)
        except Exception:
            self.handleError(record)


log_handler = WebSocketLogHandler()
log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
logging.getLogger().addHandler(log_handler)


class BotManager:
    """Administrador Singleton para gestionar el ciclo de vida del orquestador en segundo plano."""

    _instance: BotManager | None = None

    def __init__(self) -> None:
        self.orchestrator: Orchestrator | None = None
        self.db_url: str = "sqlite:///chimuelo.db"
        self.config_path: Path = Path("config/chimuelo.yaml")
        self._running: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> BotManager:
        if cls._instance is None:
            cls._instance = BotManager()
        return cls._instance

    async def start_bot(self, config_path: Path, db_url: str) -> bool:
        async with self._lock:
            if self._running:
                return False
            self.config_path = config_path
            self.db_url = db_url

            try:
                config = load_orchestrator_config(config_path)
                # Validar credenciales de Binance ANTES de lanzar el hilo executor.
                # Así el endpoint devuelve HTTP 400 inmediato si faltan las variables
                # de entorno, en vez de devolver 200 y fallar silenciosamente.
                from chimuelo_prime.api_client.models import BinanceCredentials

                BinanceCredentials.from_env()
                self.orchestrator = Orchestrator(config, db_url)
            except Exception as exc:
                logging.getLogger(__name__).error(
                    f"Error al cargar configuración o credenciales: {exc}"
                )
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            # Inicializar y arrancar en hilo secundario de forma no bloqueante
            self._running = True

            # Encapsulamos el start() en un loop sin bloqueo para FastAPI
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, self._run_orchestrator)
            return True

    def _run_orchestrator(self) -> None:
        """Función bloqueante que se ejecuta en el thread executor."""
        if self.orchestrator:
            try:
                self.orchestrator.start()
            except Exception as exc:
                logging.getLogger(__name__).critical(f"Orquestador finalizó con error: {exc}")
            finally:
                self._running = False

    async def stop_bot(self) -> bool:
        async with self._lock:
            if not self._running or not self.orchestrator:
                return False
            self._running = False  # actualizar estado inmediatamente para que el UI responda
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, self.orchestrator.stop)  # fire-and-forget
            return True

    async def panic_stop(self) -> bool:
        """Detiene el bot inmediatamente y cancela todas las órdenes activas en Binance."""
        async with self._lock:
            logger = logging.getLogger(__name__)
            logger.critical("🚨 PANIC STOP ACTIVADO: Deteniendo todo y cancelando órdenes!")

            if self.orchestrator:
                # 1. Marcar como detenido inmediatamente para que UI responda sin freeze
                self._running = False
                loop = asyncio.get_running_loop()
                loop.run_in_executor(None, self.orchestrator.stop)  # fire-and-forget

                # 2. Cancelar órdenes de Binance usando un cliente de emergencia
                try:
                    config = load_orchestrator_config(self.config_path)
                    from chimuelo_prime.api_client.models import BinanceCredentials
                    from chimuelo_prime.api_client.rate_limiter import RateLimiter
                    from chimuelo_prime.api_client.signing import BinanceSigner

                    credentials = BinanceCredentials.from_env()
                    signer = BinanceSigner(credentials=credentials)
                    rate_limiter = RateLimiter(config.api_client.rate_limit)

                    client = BinanceAuthenticatedClient(
                        base_url=config.active_env.base_url,
                        signer=signer,
                        rate_limiter=rate_limiter,
                        retry_config=config.api_client.retry,
                        timeout=config.active_env.http_timeout_seconds,
                    )

                    # Para cada símbolo, cancelar todo vía DELETE /api/v3/openOrders
                    for symbol in config.symbols:
                        logger.warning(f"Cancelando órdenes abiertas de emergencia para {symbol}")
                        try:
                            client.delete(
                                "/api/v3/openOrders",
                                params={"symbol": symbol},
                                weight=1,
                            )
                            logger.info(f"Cancelación exitosa para {symbol}")
                        except Exception as exc:
                            logger.error(f"Fallo al cancelar órdenes de {symbol}: {exc}")

                    client.close()
                except Exception as exc:
                    logger.critical(
                        f"Fallo crítico en el proceso de cancelación de emergencia: {exc}"
                    )

            return True

    def is_running(self) -> bool:
        return self._running


# Inicializar FastAPI
app = FastAPI(
    title="Chimuelo Prime Web Dashboard",
    description="Panel interactivo en tiempo real para el bot de trading Chimuelo Prime",
    version="1.0.0",
)

# Permitir CORS para desarrollo local cómodo
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StartRequest(BaseModel):
    config_path: str = "config/chimuelo.yaml"
    db_url: str = "sqlite:///data/chimuelo.db"


@app.post("/api/start")
async def start_bot_endpoint(payload: StartRequest) -> dict[str, Any]:
    manager = BotManager.get_instance()
    if manager.is_running():
        raise HTTPException(status_code=400, detail="El bot ya está en ejecución.")

    success = await manager.start_bot(Path(payload.config_path), payload.db_url)
    return {"status": "success", "message": "Bot iniciado exitosamente" if success else "Error"}


@app.post("/api/stop")
async def stop_bot_endpoint() -> dict[str, Any]:
    manager = BotManager.get_instance()
    if not manager.is_running():
        raise HTTPException(status_code=400, detail="El bot no está en ejecución.")

    success = await manager.stop_bot()
    return {"status": "success", "message": "Bot detenido limpiamente" if success else "Error"}


@app.post("/api/panic")
async def panic_stop_endpoint() -> dict[str, Any]:
    manager = BotManager.get_instance()
    await manager.panic_stop()
    return {
        "status": "success",
        "message": "Pánico ejecutado. Todas las órdenes canceladas y bot detenido.",
    }


@app.get("/api/status")
async def get_status_endpoint() -> dict[str, Any]:
    manager = BotManager.get_instance()
    is_running = manager.is_running()

    # Cargar símbolos de config o base de datos
    symbols: list[str] = []
    try:
        config = load_orchestrator_config(manager.config_path)
        symbols = config.symbols
    except Exception:
        pass

    db_data: dict[str, Any] = {}
    engine = None
    try:
        engine = create_engine(manager.db_url)
        with Session(engine) as session:
            # Si no obtuvimos símbolos de la config, deducirlos de DB
            if not symbols:
                symbols = [
                    str(r) for r in session.scalars(select(GridLevel.symbol).distinct()).all()
                ]

            for symbol in symbols:
                # 1. Obtener último Snapshot
                latest_snapshot = session.scalars(
                    select(Snapshot)
                    .where(Snapshot.symbol == symbol)
                    .order_by(Snapshot.snapshot_id.desc())
                    .limit(1)
                ).first()

                snapshot_dict = None
                if latest_snapshot:
                    snapshot_dict = {
                        "equity": str(latest_snapshot.equity),
                        "inventory": str(latest_snapshot.inventory),
                        "cash": str(latest_snapshot.cash),
                        "created_at": latest_snapshot.created_at.isoformat()
                        if latest_snapshot.created_at
                        else None,
                    }

                # 2. Obtener niveles de grid
                levels = session.scalars(
                    select(GridLevel)
                    .where(GridLevel.symbol == symbol)
                    .order_by(GridLevel.lower_price.desc())
                ).all()

                levels_list = []
                for lvl in levels:
                    buy_status = None
                    sell_status = None

                    if lvl.buy_order_id:
                        b_order = session.get(Order, lvl.buy_order_id)
                        if b_order:
                            buy_status = b_order.status
                    if lvl.sell_order_id:
                        s_order = session.get(Order, lvl.sell_order_id)
                        if s_order:
                            sell_status = s_order.status

                    # Resolver estado simple para UI
                    status = "Inactive"
                    if sell_status == "FILLED":
                        status = "FILLED_SELL"
                    elif sell_status in ("NEW", "PARTIALLY_FILLED"):
                        status = "ACTIVE_SELL"
                    elif buy_status == "FILLED":
                        status = "FILLED_BUY"
                    elif buy_status in ("NEW", "PARTIALLY_FILLED"):
                        status = "ACTIVE_BUY"
                    elif buy_status in ("CANCELED", "EXPIRED", "REJECTED"):
                        status = "CANCELED_BUY"
                    elif sell_status in ("CANCELED", "EXPIRED", "REJECTED"):
                        status = "CANCELED_SELL"

                    levels_list.append(
                        {
                            "level_id": lvl.level_id,
                            "lower_price": str(lvl.lower_price),
                            "upper_price": str(lvl.upper_price),
                            "buy_order_id": lvl.buy_order_id,
                            "sell_order_id": lvl.sell_order_id,
                            "buy_status": buy_status,
                            "sell_status": sell_status,
                            "status": status,
                        }
                    )

                db_data[symbol] = {
                    "snapshot": snapshot_dict,
                    "levels": levels_list,
                }
    except Exception as exc:
        logging.getLogger(__name__).warning(f"No se pudo consultar DB para el status: {exc}")
    finally:
        if engine:
            engine.dispose()

    return {
        "is_running": is_running,
        "symbols": symbols,
        "db_url": manager.db_url,
        "config_path": str(manager.config_path),
        "data": db_data,
    }


@app.get("/api/candles")
async def get_candles_endpoint(
    symbol: str = "SOLUSDT", interval: str = "1h", days: int = 3
) -> dict[str, Any]:
    # Siempre usar mainnet para velas históricas públicas: el testnet de Binance
    # no tiene datos OHLCV significativos y el endpoint es público (no requiere auth).
    base_url = "https://api.binance.com"

    try:
        import os

        os.makedirs("data/cache", exist_ok=True)
        loader = HistoricalDataLoader(base_url=base_url, cache_dir="data/cache")
        from datetime import UTC, datetime, timedelta

        end_time = datetime.now(UTC).replace(tzinfo=None)
        start_time = end_time - timedelta(days=days)

        # force_download=True para que el dashboard siempre muestre datos recientes
        # aunque haya un caché de otro periodo (ej. datos de backtesting).
        candles = loader.get_candles(
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            force_download=True,
        )

        serializable_candles = []
        for c in candles:
            # HistoricalCandle usa .timestamp (datetime UTC naive).
            # TradingView Lightweight Charts requiere Unix timestamps en segundos.
            serializable_candles.append(
                {
                    "time": int(c.timestamp.replace(tzinfo=UTC).timestamp()),
                    "open": float(c.open),
                    "high": float(c.high),
                    "low": float(c.low),
                    "close": float(c.close),
                    "volume": float(c.volume),
                }
            )

        # Ordenar por tiempo
        serializable_candles.sort(key=lambda x: x["time"])
        return {"symbol": symbol, "interval": interval, "candles": serializable_candles}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error al descargar velas: {exc}") from exc


@app.websocket("/api/ws")
@app.websocket("/ws/live")
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    manager = BotManager.get_instance()

    # Registrar el WS listener para recibir logs en vivo
    queue: asyncio.Queue[str] = asyncio.Queue()
    loop = asyncio.get_event_loop()  # capturado en contexto async; seguro desde threads de executor

    def listener(msg: str) -> None:
        # Despachar mensaje al queue de este WS
        try:
            loop.call_soon_threadsafe(queue.put_nowait, msg)
        except Exception:
            pass

    log_handler.listeners.add(listener)

    # Enviar logs históricos al conectar para rellenar consola del frontend
    for msg in list(log_handler.log_queue):
        try:
            await websocket.send_json({"type": "log", "message": msg})
        except Exception:
            break

    try:
        # Tarea de lectura del WS
        async def read_ws() -> None:
            try:
                while True:
                    # Simplemente descartar mensajes entrantes o leer pings
                    await websocket.receive_text()
            except (WebSocketDisconnect, RuntimeError):
                pass

        # Tarea de escritura de logs y estado periódico
        async def write_ws() -> None:
            last_status_sent = 0.0
            try:
                while True:
                    # 1. Esperar logs
                    try:
                        # timeout pequeño para poder mandar actualizaciones de estado periódicas
                        msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                        await websocket.send_json({"type": "log", "message": msg})
                    except TimeoutError:
                        pass

                    # 2. Enviar actualización rápida de estado cada 3 segundos
                    now = asyncio.get_event_loop().time()
                    if now - last_status_sent >= 3.0:
                        status = {
                            "type": "status",
                            "is_running": manager.is_running(),
                        }
                        await websocket.send_json(status)
                        last_status_sent = now
            except (WebSocketDisconnect, RuntimeError):
                pass

        # Correr ambas de forma concurrente
        await asyncio.gather(read_ws(), write_ws())

    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        log_handler.listeners.remove(listener)


@app.get("/")
async def get_index() -> FileResponse:
    return FileResponse(str(Path(__file__).parent / "web" / "index.html"))


# Montar la carpeta de estáticos web (HTML/CSS/JS)
web_dir = Path(__file__).parent / "web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
