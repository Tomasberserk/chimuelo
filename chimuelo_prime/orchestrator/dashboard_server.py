"""Servidor Backend de FastAPI y WebSockets para el Dashboard Web de Chimuelo Prime.

Proporciona una interfaz REST y WebSockets reactiva de alto rendimiento para:
1. Consultar velas de mercado (Klines) con indicadores técnicos cuantitativos
   precalculados con pureza Decimal (EMA 200, EMA 20, RSI 14, ATR 14).
2. Consultar datos de ticker 24hr de Binance.
3. Monitorear y controlar el ciclo de vida del motor de Paper Trading (PaperTradingEngine + VirtualBroker).
4. Servir actualizaciones y eventos de trading en tiempo real a través de WebSockets (/ws/live).
5. Servir la interfaz visual estática del dashboard.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from chimuelo_prime.exchange_config.exceptions import ExchangeUnreachableError
from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.orchestrator.monitoring import AlertManager
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
from chimuelo_prime.strategies.indicators import (
    calculate_atr,
    calculate_ema,
    calculate_rsi,
)
from chimuelo_prime.strategies.rsi_divergence import RSIDivergenceStrategy
from chimuelo_prime.strategies.sentiment_service import MacroSentimentService

logger = get_logger(__name__)
sentiment_service = MacroSentimentService()

# ==============================================================================
# MODELOS PYDANTIC PARA REQUESTS Y RESPONSES DE LA API
# ==============================================================================


class PaperStartRequest(BaseModel):
    """Payload de solicitud para iniciar el motor de Paper Trading."""

    model_config = ConfigDict(strict=True)

    symbol: str = Field(default="SOLUSDT", description="Símbolo del par a operar")
    interval: str = Field(default="15m", description="Temporalidad de velas (ej. 15m, 1h)")
    initial_balance: Decimal = Field(
        default=Decimal("25.00"),
        description="Balance inicial de la micro-cuenta en USDT",
    )
    poll_interval: float = Field(
        default=10.0,
        description="Segundos entre cada ciclo de sondeo del mercado",
    )
    report_interval: float = Field(
        default=3600.0,
        description="Segundos entre resúmenes de portafolio",
    )
    candle_limit: int = Field(
        default=300,
        description="Límite de velas a descargar para el cálculo de indicadores",
    )

    @field_validator("initial_balance", mode="before")
    @classmethod
    def reject_floats(cls, v: Any) -> Any:
        if isinstance(v, float):
            raise TypeError(f"Floats no permitidos en modelos financieros: {v!r}")
        if v is not None and not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class KlineCandleItem(BaseModel):
    """Representación de una vela formateada para TradingView Lightweight Charts."""

    time: int = Field(description="Timestamp Unix en segundos (open time)")
    open: float = Field(description="Precio de apertura")
    high: float = Field(description="Precio máximo")
    low: float = Field(description="Precio mínimo")
    close: float = Field(description="Precio de cierre")
    volume: float = Field(description="Volumen transaccionado")
    ema200: float | None = Field(default=None, description="Media Móvil Exponencial de 200 periodos")
    ema20: float | None = Field(default=None, description="Media Móvil Exponencial de 20 periodos")
    rsi: float | None = Field(default=None, description="Relative Strength Index (14 periodos)")
    atr: float | None = Field(default=None, description="Average True Range (14 periodos)")


class KlinesResponse(BaseModel):
    """Respuesta estructurada para velas históricas con indicadores técnicos."""

    symbol: str
    interval: str
    count: int
    candles: list[KlineCandleItem]


# ==============================================================================
# GESTOR DE PAPER TRADING (SINGLETON / SERVICE MANAGER)
# ==============================================================================


class PaperTradingManager:
    """Administrador centralizado para el ciclo de vida de Paper Trading."""

    _instance: PaperTradingManager | None = None

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._symbol: str = "SOLUSDT"
        self._interval: str = "1h"
        self._initial_balance: Decimal = Decimal("100.00")
        self._alert_manager = AlertManager()
        self._db_url: str = "sqlite:///chimuelo.db"
        from chimuelo_prime.grid_state.database import build_engine
        self._db_engine = build_engine(self._db_url)
        self._broker = VirtualBroker(
            initial_balance=self._initial_balance,
            alert_manager=self._alert_manager,
            db_engine=self._db_engine,
            db_url=self._db_url,
        )
        self._strategy = RSIDivergenceStrategy(
            symbol=self._symbol,
            rsi_oversold_threshold=Decimal("38.0"),
            lookback_bars=30,
            volume_multiplier=Decimal("1.1"),
            atr_sl_multiplier=Decimal("1.2"),
            risk_reward_ratio=Decimal("2.0"),
            macro_sentiment_service=sentiment_service,
        )
        self._engine: PaperTradingEngine | None = None
        self._thread: threading.Thread | None = None
        self._is_running: bool = False
        self._last_price: Decimal | None = None

    @classmethod
    def get_instance(cls) -> PaperTradingManager:
        """Obtiene o crea la instancia singleton de PaperTradingManager."""
        if cls._instance is None:
            cls._instance = PaperTradingManager()
        return cls._instance

    @property
    def is_running(self) -> bool:
        """Indica si el motor de Paper Trading está activo."""
        return self._is_running

    @property
    def symbol(self) -> str:
        """Símbolo actual configurado."""
        return self._symbol

    @property
    def interval(self) -> str:
        """Intervalo de velas configurado."""
        return self._interval

    @property
    def broker(self) -> VirtualBroker:
        """Instancia activa del VirtualBroker."""
        return self._broker

    @property
    def engine(self) -> PaperTradingEngine | None:
        """Instancia activa del PaperTradingEngine."""
        return self._engine

    def start(
        self,
        symbol: str = "SOLUSDT",
        interval: str = "1h",
        initial_balance: Decimal = Decimal("100.00"),
        poll_interval: float = 10.0,
        report_interval: float = 3600.0,
        candle_limit: int = 300,
        session: requests.Session | None = None,
    ) -> bool:
        """Inicia el motor de Paper Trading en un hilo de fondo.

        Returns:
            True si se inició exitosamente, False si ya estaba en ejecución.
        """
        with self._lock:
            if self._is_running:
                return False

            self._symbol = symbol.upper()
            self._interval = interval
            self._initial_balance = Decimal(str(initial_balance))

            config = PaperTradingConfig(
                symbol=self._symbol,
                interval=self._interval,
                initial_balance=self._initial_balance,
                poll_interval_seconds=poll_interval,
                report_interval_seconds=report_interval,
                candle_limit=candle_limit,
            )

            self._broker = VirtualBroker(
                initial_balance=config.initial_balance,
                fee_rate=config.fee_rate,
                slippage_pct=config.slippage_pct,
                min_notional=config.min_notional,
                alert_manager=self._alert_manager,
                db_url=self._db_url,
            )

            self._strategy = RSIDivergenceStrategy(
                symbol=self._symbol,
                rsi_oversold_threshold=Decimal("38.0"),
                lookback_bars=30,
                volume_multiplier=Decimal("1.1"),
                atr_sl_multiplier=Decimal("1.2"),
                risk_reward_ratio=Decimal("2.0"),
                macro_sentiment_service=sentiment_service,
            )

            self._engine = PaperTradingEngine(
                config=config,
                broker=self._broker,
                strategy=self._strategy,
                alert_manager=self._alert_manager,
                session=session,
            )

            self._is_running = True
            self._thread = threading.Thread(target=self._run_worker, daemon=True)
            self._thread.start()
            logger.info("dashboard.paper_trading_started", symbol=self._symbol, interval=self._interval)
            return True

    def _run_worker(self) -> None:
        """Bucle de ejecución ejecutado en segundo plano."""
        try:
            if self._engine:
                self._engine.start()
        except Exception as exc:
            logger.error("dashboard.paper_worker_error", error=str(exc))
        finally:
            self._is_running = False

    def stop(self) -> bool:
        """Detiene el motor de Paper Trading de forma ordenada.

        Returns:
            True si se detuvo, False si no estaba en ejecución.
        """
        with self._lock:
            if not self._is_running:
                return False

            if self._engine:
                self._engine.stop()

            self._is_running = False
            logger.info("dashboard.paper_trading_stopped", symbol=self._symbol)
            return True

    def get_status(self, current_price: Decimal | None = None) -> dict[str, Any]:
        """Obtiene un diccionario con el estado actual consolidado del broker y motor."""
        prices = {self._symbol: current_price} if current_price is not None else None
        state = self._broker.get_state(prices)
        pos = self._broker.get_position(self._symbol)

        open_pos_dict: dict[str, Any] | None = None
        if pos is not None:
            mark = current_price or pos.entry_price
            unrealized_pnl = pos.qty * (mark - pos.entry_price)
            notional = pos.qty * pos.entry_price
            unrealized_pct = (
                (unrealized_pnl / notional * Decimal("100"))
                if notional > Decimal("0")
                else Decimal("0")
            )
            open_pos_dict = {
                "symbol": pos.symbol,
                "side": "BUY",
                "entry_price": float(pos.entry_price),
                "qty": float(pos.qty),
                "notional": float(notional),
                "stop_loss": float(pos.stop_loss),
                "take_profit": float(pos.take_profit),
                "entry_time": pos.entry_time.isoformat() if hasattr(pos.entry_time, "isoformat") else str(pos.entry_time),
                "current_price": float(mark),
                "unrealized_pnl": float(unrealized_pnl),
                "unrealized_pnl_pct": float(unrealized_pct),
                "initial_risk_usd": float(pos.initial_risk_usd) if pos.initial_risk_usd is not None else None,
            }

        trades = self._broker.trade_history
        total_trades = len(trades)
        wins = sum(1 for t in trades if t.net_pnl > Decimal("0"))
        win_rate = (float(wins) / float(total_trades) * 100.0) if total_trades > 0 else 0.0

        return {
            "is_running": self._is_running,
            "symbol": self._symbol,
            "interval": self._interval,
            "balance": float(state.cash),
            "equity": float(state.equity),
            "open_position": open_pos_dict,
            "pnl": float(state.total_realized_pnl),
            "win_rate": round(win_rate, 2),
            "total_trades": total_trades,
        }

    def get_trades(self) -> list[dict[str, Any]]:
        """Retorna el historial completo de operaciones de paper trading."""
        trades_list: list[dict[str, Any]] = []
        for t in self._broker.trade_history:
            trades_list.append(
                {
                    "trade_id": t.trade_id,
                    "symbol": t.symbol,
                    "side": t.side,
                    "entry_time": t.entry_time.isoformat() if hasattr(t.entry_time, "isoformat") else str(t.entry_time),
                    "exit_time": t.exit_time.isoformat() if hasattr(t.exit_time, "isoformat") else str(t.exit_time),
                    "entry_price": float(t.entry_price),
                    "exit_price": float(t.exit_price),
                    "qty": float(t.qty),
                    "notional": float(t.notional),
                    "stop_loss": float(t.stop_loss),
                    "take_profit": float(t.take_profit),
                    "gross_pnl": float(t.gross_pnl),
                    "total_fees": float(t.total_fees),
                    "net_pnl": float(t.net_pnl),
                    "net_pnl_pct": float(t.net_pnl_pct),
                    "exit_reason": t.exit_reason,
                    "reason": t.reason,
                }
            )
        return trades_list

    def reset(self, initial_balance: Decimal = Decimal("25.00")) -> None:
        """Reinicia el estado del gestor (útil para pruebas unitarias)."""
        self.stop()
        self._symbol = "SOLUSDT"
        self._interval = "15m"
        self._initial_balance = Decimal(str(initial_balance))
        self._broker = VirtualBroker(
            initial_balance=self._initial_balance,
            alert_manager=self._alert_manager,
        )
        self._strategy = RSIDivergenceStrategy(symbol=self._symbol)
        self._engine = None
        self._thread = None
        self._is_running = False
        self._last_price = None


# ==============================================================================
# GESTOR DE CONEXIONES WEBSOCKET
# ==============================================================================


class LiveWebSocketManager:
    """Maneja las conexiones activas al WebSocket /ws/live y la difusión de updates."""

    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Acepta y registra una nueva conexión WebSocket."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        """Elimina una conexión WebSocket desconectada."""
        async with self._lock:
            self.active_connections.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Difunde un mensaje JSON a todos los clientes conectados."""
        async with self._lock:
            disconnected: list[WebSocket] = []
            for ws in self.active_connections:
                try:
                    await ws.send_json(message)
                except Exception:
                    disconnected.append(ws)

            for ws in disconnected:
                self.active_connections.discard(ws)


ws_manager = LiveWebSocketManager()


# ==============================================================================
# APLICACIÓN FASTAPI Y RUTAS
# ==============================================================================

app = FastAPI(
    title="Chimuelo Prime Dashboard Server",
    description="Servidor REST y WebSockets de Alta Fidelidad para Trading Cuantitativo y Paper Trading.",
    version="1.0.0",
)

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event() -> None:
    """Inicia automáticamente el motor de Paper Trading al levantar el servidor."""
    manager = PaperTradingManager.get_instance()
    if not manager.is_running:
        manager.start()
        logger.info("dashboard.auto_started_paper_trading")


@app.get("/api/candles", response_model=KlinesResponse)
@app.get("/api/market/klines", response_model=KlinesResponse)
def get_market_klines(
    symbol: str = Query("SOLUSDT", description="Símbolo del par (ej. SOLUSDT)"),
    interval: str = Query("1h", description="Intervalo temporal (ej. 15m, 1h, 4h, 1d)"),
    limit: int = Query(300, ge=1, le=1000, description="Cantidad de velas a descargar"),
    days: int | None = Query(None, description="Días de historial (opcional)"),
) -> dict[str, Any]:
    """Retorna velas reales de Binance formateadas para TradingView con indicadores precalculados.

    Calcula de forma determinista y con pureza Decimal:
    - EMA 200
    - EMA 20
    - RSI 14 (Wilder's Smoothing)
    - ATR 14 (Wilder's Smoothing)
    """
    sym = symbol.upper()
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": sym,
        "interval": interval,
        "limit": limit,
    }

    try:
        response = requests.get(url, params=params, timeout=10.0)
        response.raise_for_status()
        raw_data = response.json()
    except requests.exceptions.RequestException as exc:
        logger.error("dashboard.binance_klines_failed", symbol=sym, error=str(exc))
        raise HTTPException(
            status_code=502,
            detail=f"Error al conectar con la API de Binance para Klines de {sym}: {exc}",
        ) from exc

    if not isinstance(raw_data, list):
        raise HTTPException(
            status_code=502,
            detail=f"Respuesta inesperada de Binance para {sym}: {raw_data!r}",
        )

    # Extraer series cronológicas con Decimal puro
    highs: list[Decimal] = []
    lows: list[Decimal] = []
    closes: list[Decimal] = []

    for item in raw_data:
        try:
            highs.append(Decimal(str(item[2])))
            lows.append(Decimal(str(item[3])))
            closes.append(Decimal(str(item[4])))
        except (IndexError, ValueError) as err:
            raise HTTPException(
                status_code=502,
                detail=f"Datos de velas corruptos recibidos de Binance: {err}",
            ) from err

    # Precalcular indicadores cuantitativos
    ema200_series = calculate_ema(closes, 200)
    ema20_series = calculate_ema(closes, 20)
    rsi_series = calculate_rsi(closes, 14)
    atr_series = calculate_atr(highs, lows, closes, 14)

    # Estructurar velas para TradingView
    candles: list[dict[str, Any]] = []
    for i, item in enumerate(raw_data):
        open_time_ms = int(item[0])
        time_sec = open_time_ms // 1000

        ema200_val = float(ema200_series[i]) if ema200_series[i] is not None else None
        ema20_val = float(ema20_series[i]) if ema20_series[i] is not None else None
        rsi_val = float(rsi_series[i]) if rsi_series[i] is not None else None
        atr_val = float(atr_series[i]) if atr_series[i] is not None else None

        candles.append(
            {
                "time": time_sec,
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
                "ema200": ema200_val,
                "ema20": ema20_val,
                "rsi": rsi_val,
                "atr": atr_val,
            }
        )

    return {
        "symbol": sym,
        "interval": interval,
        "count": len(candles),
        "candles": candles,
    }


@app.get("/api/market/ticker")
def get_market_ticker(
    symbol: str = Query("SOLUSDT", description="Símbolo del par (ej. SOLUSDT)"),
) -> dict[str, Any]:
    """Retorna datos 24h ticker en vivo de Binance (/api/v3/ticker/24hr)."""
    sym = symbol.upper()
    url = "https://api.binance.com/api/v3/ticker/24hr"
    params = {"symbol": sym}

    try:
        response = requests.get(url, params=params, timeout=10.0)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as exc:
        logger.error("dashboard.binance_ticker_failed", symbol=sym, error=str(exc))
        raise HTTPException(
            status_code=502,
            detail=f"Error al conectar con la API de Binance para Ticker de {sym}: {exc}",
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=502,
            detail=f"Respuesta inesperada de Binance para Ticker de {sym}: {data!r}",
        )

    return {
        "symbol": data.get("symbol", sym),
        "priceChange": float(data.get("priceChange", 0.0)),
        "priceChangePercent": float(data.get("priceChangePercent", 0.0)),
        "lastPrice": float(data.get("lastPrice", 0.0)),
        "highPrice": float(data.get("highPrice", 0.0)),
        "lowPrice": float(data.get("lowPrice", 0.0)),
        "volume": float(data.get("volume", 0.0)),
        "quoteVolume": float(data.get("quoteVolume", 0.0)),
        "openTime": data.get("openTime"),
        "closeTime": data.get("closeTime"),
        "raw": data,
    }


@app.get("/api/status")
@app.get("/api/paper/status")
def get_paper_status() -> dict[str, Any]:
    """Retorna el estado consolidado actual de PaperTradingEngine y VirtualBroker."""
    manager = PaperTradingManager.get_instance()
    return manager.get_status()


@app.post("/api/start")
@app.post("/api/paper/start")
def start_paper_trading(payload: PaperStartRequest | None = None) -> dict[str, Any]:
    """Inicia la ejecución en background de PaperTradingEngine para el símbolo e intervalo solicitados."""
    manager = PaperTradingManager.get_instance()
    req = payload or PaperStartRequest()

    if manager.is_running:
        return {
            "status": "already_running",
            "message": f"El motor de Paper Trading ya está en ejecución ({manager.symbol}, {manager.interval}).",
            "symbol": manager.symbol,
            "interval": manager.interval,
        }

    started = manager.start(
        symbol=req.symbol,
        interval=req.interval,
        initial_balance=req.initial_balance,
        poll_interval=req.poll_interval,
        report_interval=req.report_interval,
        candle_limit=req.candle_limit,
    )

    if not started:
        return {
            "status": "already_running",
            "message": "El motor de Paper Trading ya se encuentra activo.",
            "symbol": manager.symbol,
        }

    return {
        "status": "started",
        "message": "Motor de Paper Trading iniciado exitosamente en segundo plano.",
        "symbol": req.symbol.upper(),
        "interval": req.interval,
        "initial_balance": float(req.initial_balance),
    }


@app.post("/api/panic")
@app.post("/api/stop")
@app.post("/api/paper/stop")
def stop_paper_trading() -> dict[str, Any]:
    """Detiene la ejecución en background de PaperTradingEngine."""
    manager = PaperTradingManager.get_instance()

    if not manager.is_running:
        return {
            "status": "not_running",
            "message": "El motor de Paper Trading no está en ejecución.",
        }

    manager.stop()
    return {
        "status": "stopped",
        "message": "Motor de Paper Trading detenido exitosamente.",
    }


@app.get("/api/trades")
@app.get("/api/paper/trades")
def get_paper_trades() -> dict[str, Any]:
    """Retorna el historial de operaciones cerradas de paper trading con PnL y exit reason."""
    manager = PaperTradingManager.get_instance()
    trades = manager.get_trades()
    return {
        "trades": trades,
        "total_trades": len(trades),
    }


@app.get("/api/sentiment")
@app.get("/api/market/sentiment")
def get_market_sentiment() -> dict[str, Any]:
    """Retorna el reporte en vivo de sentimiento macro (Crypto Fear & Greed Index + Régimen Macro)."""
    report = sentiment_service.get_sentiment_report()
    return {
        "score": float(report.score),
        "category": report.category.value,
        "macro_regime": report.macro_regime.value,
        "can_open_longs": report.can_open_longs,
        "veto_reason": report.veto_reason,
        "source": report.source,
        "timestamp": report.timestamp.isoformat(),
        "macro_summary": report.macro_summary,
    }


@app.websocket("/ws")
@app.websocket("/api/ws")
@app.websocket("/ws/live")
async def live_websocket_endpoint(websocket: WebSocket) -> None:
    """Stream WebSocket en tiempo real con updates periódicos de precios, velas, posición y estado de cuenta."""
    await ws_manager.connect(websocket)
    manager = PaperTradingManager.get_instance()

    try:
        # Enviar estado inicial inmediato al cliente
        initial_status = manager.get_status()
        await websocket.send_json(
            {
                "type": "connection_established",
                "symbol": manager.symbol,
                "status": initial_status,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        async def read_incoming() -> None:
            """Lee mensajes o pings entrantes del cliente."""
            try:
                while True:
                    text = await websocket.receive_text()
                    if text == "ping":
                        await websocket.send_json({"type": "pong", "timestamp": datetime.now(UTC).isoformat()})
            except (WebSocketDisconnect, RuntimeError):
                pass

        async def stream_live_updates() -> None:
            """Transmite updates de mercado y cuenta cada segundo."""
            try:
                while True:
                    await asyncio.sleep(1.0)
                    status = manager.get_status()
                    engine = manager.engine
                    last_result = engine.last_cycle_result if engine else None

                    update_payload: dict[str, Any] = {
                        "type": "live_update",
                        "timestamp": datetime.now(UTC).isoformat(),
                        "symbol": manager.symbol,
                        "interval": manager.interval,
                        "is_running": manager.is_running,
                        "account": {
                            "balance": status["balance"],
                            "equity": status["equity"],
                            "realized_pnl": status["pnl"],
                            "win_rate": status["win_rate"],
                            "total_trades": status["total_trades"],
                        },
                        "position": status["open_position"],
                    }

                    try:
                        sent_rep = sentiment_service.get_sentiment_report()
                        update_payload["sentiment"] = {
                            "score": float(sent_rep.score),
                            "category": sent_rep.category.value,
                            "macro_regime": sent_rep.macro_regime.value,
                            "can_open_longs": sent_rep.can_open_longs,
                            "veto_reason": sent_rep.veto_reason,
                            "summary": sent_rep.macro_summary,
                        }
                    except Exception:
                        pass

                    if last_result is not None:
                        update_payload["last_price"] = float(last_result.current_price)
                        update_payload["is_new_candle"] = last_result.is_new_candle

                    await websocket.send_json(update_payload)
            except (WebSocketDisconnect, RuntimeError):
                pass

        await asyncio.gather(read_incoming(), stream_live_updates())

    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await ws_manager.disconnect(websocket)


# ==============================================================================
# MONTAJE DE ARCHIVOS ESTÁTICOS DEL DASHBOARD WEB
# ==============================================================================

web_dir = Path(__file__).parent / "web"

if web_dir.exists():
    @app.get("/")
    async def serve_index() -> FileResponse:
        """Sirve el index.html del Dashboard Web."""
        return FileResponse(str(web_dir / "index.html"))

    @app.get("/dashboard")
    async def serve_dashboard() -> FileResponse:
        """Ruta alternativa para acceder al Dashboard."""
        return FileResponse(str(web_dir / "index.html"))

    # Montar en /static y en / para soporte completo sin errores 404
    app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")


