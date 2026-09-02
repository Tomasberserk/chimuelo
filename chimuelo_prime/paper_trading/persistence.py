"""Capa de Persistencia Durable y Almacenamiento Idempotente para Paper Trading."""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from chimuelo_prime.paper_trading.decision_models import (
    DecisionAction,
    DecisionObject,
    PaperFill,
    PaperOrder,
    PaperPosition,
    RiskStateEnum,
    RiskStateSnapshot,
    ensure_utc_aware,
)


class DuplicateDecisionError(Exception):
    """Lanzada cuando se intenta registrar una decisión duplicada para el mismo símbolo y timestamp."""


class DuplicateOrderError(Exception):
    """Lanzada cuando se intenta crear una orden duplicada para una misma decisión."""


class BasePersistenceBackend(ABC):
    """Interfaz abstracta para almacenamiento durable."""

    @abstractmethod
    def save_decision(self, decision: DecisionObject) -> None:
        pass

    @abstractmethod
    def save_paper_order(self, order: PaperOrder) -> None:
        pass

    @abstractmethod
    def save_paper_fill(self, fill: PaperFill) -> None:
        pass

    @abstractmethod
    def save_paper_position(self, position: PaperPosition) -> None:
        pass

    @abstractmethod
    def update_paper_position(self, position: PaperPosition) -> None:
        pass

    @abstractmethod
    def get_open_positions(self) -> list[PaperPosition]:
        pass

    @abstractmethod
    def get_last_processed_timestamp(self, symbol: str) -> datetime | None:
        pass

    @abstractmethod
    def get_decision_by_timestamp(self, symbol: str, timestamp: datetime) -> DecisionObject | None:
        pass


class SQLitePersistenceBackend(BasePersistenceBackend):
    """Backend SQLite local idempotente para desarrollo, replay y testing."""

    def __init__(self, db_path: str = "data/paper_trading.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS evaluation_decisions (
                    decision_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    action TEXT NOT NULL,
                    why_signal TEXT NOT NULL,
                    why_allowed TEXT NOT NULL,
                    why_blocked TEXT NOT NULL,
                    candle_close TEXT NOT NULL,
                    candle_volume TEXT NOT NULL,
                    suggested_entry TEXT,
                    suggested_sl TEXT,
                    suggested_tp TEXT,
                    suggested_qty TEXT,
                    data_snapshot_hash TEXT NOT NULL,
                    raw_payload_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, timestamp)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_orders (
                    order_id TEXT PRIMARY KEY,
                    decision_id TEXT UNIQUE NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    requested_price TEXT NOT NULL,
                    stop_loss TEXT NOT NULL,
                    take_profit TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    risk_pct_used TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_fills (
                    fill_id TEXT PRIMARY KEY,
                    order_id TEXT UNIQUE NOT NULL,
                    decision_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    signal_price TEXT NOT NULL,
                    fill_price TEXT NOT NULL,
                    slippage_pct TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    fee_usd TEXT NOT NULL,
                    fee_rate TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_positions (
                    position_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    status TEXT NOT NULL,
                    entry_time TEXT NOT NULL,
                    entry_signal_price TEXT NOT NULL,
                    fill_price TEXT NOT NULL,
                    slippage_pct TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    stop_loss TEXT NOT NULL,
                    take_profit TEXT NOT NULL,
                    fee_entry TEXT NOT NULL,
                    exit_time TEXT,
                    exit_price TEXT,
                    exit_reason TEXT,
                    fee_exit TEXT,
                    gross_pnl TEXT,
                    net_pnl TEXT,
                    r_multiple TEXT,
                    duration_hours INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS risk_state_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    current_state TEXT NOT NULL,
                    equity TEXT NOT NULL,
                    high_water_mark TEXT NOT NULL,
                    daily_dd_pct TEXT NOT NULL,
                    peak_dd_pct TEXT NOT NULL,
                    consecutive_losses INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def save_decision(self, decision: DecisionObject) -> None:
        ts_str = decision.timestamp.isoformat()
        with self._get_connection() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO evaluation_decisions (
                        decision_id, timestamp, symbol, timeframe, strategy_version, config_hash,
                        action, why_signal, why_allowed, why_blocked, candle_close, candle_volume,
                        suggested_entry, suggested_sl, suggested_tp, suggested_qty, data_snapshot_hash,
                        raw_payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision.decision_id,
                        ts_str,
                        decision.symbol,
                        decision.timeframe,
                        decision.strategy_version,
                        decision.config_hash,
                        decision.action.value,
                        decision.why_signal,
                        decision.why_allowed,
                        decision.why_blocked,
                        str(decision.candle_close),
                        str(decision.candle_volume),
                        str(decision.suggested_entry_price) if decision.suggested_entry_price else None,
                        str(decision.suggested_stop_loss) if decision.suggested_stop_loss else None,
                        str(decision.suggested_take_profit) if decision.suggested_take_profit else None,
                        str(decision.suggested_quantity) if decision.suggested_quantity else None,
                        decision.data_snapshot_hash,
                        decision.model_dump_json(),
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError as err:
                raise DuplicateDecisionError(
                    f"Decisión duplicada detectada para {decision.symbol} en {ts_str}"
                ) from err

    def save_paper_order(self, order: PaperOrder) -> None:
        with self._get_connection() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO paper_orders (
                        order_id, decision_id, symbol, side, timestamp, requested_price,
                        stop_loss, take_profit, quantity, risk_pct_used
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order.order_id,
                        order.decision_id,
                        order.symbol,
                        order.side,
                        order.timestamp.isoformat(),
                        str(order.requested_price),
                        str(order.stop_loss),
                        str(order.take_profit),
                        str(order.quantity),
                        str(order.risk_pct_used),
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError as err:
                raise DuplicateOrderError(f"Orden duplicada para decision_id {order.decision_id}") from err

    def save_paper_fill(self, fill: PaperFill) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO paper_fills (
                    fill_id, order_id, decision_id, symbol, timestamp, signal_price,
                    fill_price, slippage_pct, quantity, fee_usd, fee_rate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fill.fill_id,
                    fill.order_id,
                    fill.decision_id,
                    fill.symbol,
                    fill.timestamp.isoformat(),
                    str(fill.signal_price),
                    str(fill.fill_price),
                    str(fill.slippage_pct),
                    str(fill.quantity),
                    str(fill.fee_usd),
                    str(fill.fee_rate),
                ),
            )
            conn.commit()

    def save_paper_position(self, position: PaperPosition) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO paper_positions (
                    position_id, symbol, status, entry_time, entry_signal_price, fill_price,
                    slippage_pct, quantity, stop_loss, take_profit, fee_entry, exit_time,
                    exit_price, exit_reason, fee_exit, gross_pnl, net_pnl, r_multiple, duration_hours
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    position.position_id,
                    position.symbol,
                    position.status,
                    position.entry_time.isoformat(),
                    str(position.entry_signal_price),
                    str(position.fill_price),
                    str(position.slippage_pct),
                    str(position.quantity),
                    str(position.stop_loss),
                    str(position.take_profit),
                    str(position.fee_entry),
                    position.exit_time.isoformat() if position.exit_time else None,
                    str(position.exit_price) if position.exit_price else None,
                    position.exit_reason,
                    str(position.fee_exit) if position.fee_exit else None,
                    str(position.gross_pnl) if position.gross_pnl else None,
                    str(position.net_pnl) if position.net_pnl else None,
                    str(position.r_multiple) if position.r_multiple else None,
                    position.duration_hours,
                ),
            )
            conn.commit()

    def update_paper_position(self, position: PaperPosition) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE paper_positions SET
                    status = ?,
                    exit_time = ?,
                    exit_price = ?,
                    exit_reason = ?,
                    fee_exit = ?,
                    gross_pnl = ?,
                    net_pnl = ?,
                    r_multiple = ?,
                    duration_hours = ?
                WHERE position_id = ?
                """,
                (
                    position.status,
                    position.exit_time.isoformat() if position.exit_time else None,
                    str(position.exit_price) if position.exit_price else None,
                    position.exit_reason,
                    str(position.fee_exit) if position.fee_exit else None,
                    str(position.gross_pnl) if position.gross_pnl else None,
                    str(position.net_pnl) if position.net_pnl else None,
                    str(position.r_multiple) if position.r_multiple else None,
                    position.duration_hours,
                    position.position_id,
                ),
            )
            conn.commit()

    def get_open_positions(self) -> list[PaperPosition]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM paper_positions WHERE status = 'OPEN'")
            rows = cur.fetchall()
            positions = []
            for r in rows:
                positions.append(
                    PaperPosition(
                        position_id=r["position_id"],
                        symbol=r["symbol"],
                        status=r["status"],
                        entry_time=datetime.fromisoformat(r["entry_time"]),
                        entry_signal_price=Decimal(r["entry_signal_price"]),
                        fill_price=Decimal(r["fill_price"]),
                        slippage_pct=Decimal(r["slippage_pct"]),
                        quantity=Decimal(r["quantity"]),
                        stop_loss=Decimal(r["stop_loss"]),
                        take_profit=Decimal(r["take_profit"]),
                        fee_entry=Decimal(r["fee_entry"]),
                    )
                )
            return positions

    def get_last_processed_timestamp(self, symbol: str) -> datetime | None:
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT timestamp FROM evaluation_decisions WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
                (symbol,),
            )
            row = cur.fetchone()
            if row:
                return datetime.fromisoformat(row["timestamp"])
            return None

    def get_decision_by_timestamp(self, symbol: str, timestamp: datetime) -> DecisionObject | None:
        ts_str = ensure_utc_aware(timestamp).isoformat()
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT raw_payload_json FROM evaluation_decisions WHERE symbol = ? AND timestamp = ?",
                (symbol, ts_str),
            )
            row = cur.fetchone()
            if row:
                return DecisionObject.model_validate_json(row["raw_payload_json"])
            return None
