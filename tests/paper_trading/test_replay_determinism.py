"""Tests de determinismo estricto para validar que Live(t) == Replay(t)."""

from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.paper_trading.live_runner import LivePaperRunner
from chimuelo_prime.paper_trading.persistence import SQLitePersistenceBackend
from chimuelo_prime.paper_trading.replay_harness import ReplayHarness


def load_sample_candles_1h(symbol: str, count: int = 150) -> list[HistoricalCandle]:
    cache_file = Path("data/cache_extended") / f"{symbol}_1h.json"
    with open(cache_file, encoding="utf-8") as f:
        raw = json.load(f)
    candles = [
        HistoricalCandle(
            timestamp=datetime.fromtimestamp(item[0] / 1000.0, tz=UTC),
            open=Decimal(str(item[1])),
            high=Decimal(str(item[2])),
            low=Decimal(str(item[3])),
            close=Decimal(str(item[4])),
            volume=Decimal(str(item[5])),
        )
        for item in raw[:count]
    ]
    return candles


def load_sample_daily_candles() -> list[HistoricalCandle]:
    cache_file = Path("data/cache_extended") / "BTCUSDT_1h.json"
    with open(cache_file, encoding="utf-8") as f:
        raw = json.load(f)
    # Agrupar en diarias
    candles_1h = [
        HistoricalCandle(
            timestamp=datetime.fromtimestamp(item[0] / 1000.0, tz=UTC),
            open=Decimal(str(item[1])),
            high=Decimal(str(item[2])),
            low=Decimal(str(item[3])),
            close=Decimal(str(item[4])),
            volume=Decimal(str(item[5])),
        )
        for item in raw[:600]
    ]
    from chimuelo_prime.paper_trading.persistence import ensure_utc_aware
    daily = []
    curr = []
    for c in candles_1h:
        if not curr:
            curr.append(c)
        elif c.timestamp.date() == curr[0].timestamp.date():
            curr.append(c)
        else:
            daily.append(
                HistoricalCandle(
                    timestamp=curr[0].timestamp.replace(hour=0, minute=0, second=0),
                    open=curr[0].open,
                    high=max(x.high for x in curr),
                    low=min(x.low for x in curr),
                    close=curr[-1].close,
                    volume=sum(x.volume for x in curr),
                )
            )
            curr = [c]
    return daily


def test_live_equals_replay_field_by_field(tmp_path):
    """Verifica que Replay(t) == Live(t) campo por campo sobre una serie de 120 barras."""
    sol_candles = load_sample_candles_1h("SOLUSDT", 130)
    btc_daily = load_sample_daily_candles()

    db_replay = str(tmp_path / "replay.db")
    db_live = str(tmp_path / "live.db")

    # 1. Ejecutar Replay
    replay_harness = ReplayHarness(symbol="SOLUSDT", db_path=db_replay)
    replay_decisions = replay_harness.run_replay(
        candles_1h=sol_candles,
        btc_daily_candles=btc_daily,
        execute_paper=True,
    )

    # 2. Ejecutar Live Runner
    live_persistence = SQLitePersistenceBackend(db_live)
    live_runner = LivePaperRunner(
        symbols=["SOLUSDT"],
        persistence=live_persistence,
        shadow_only=False,
    )

    live_decisions = []
    for idx in range(100, len(sol_candles)):
        buffer_window = sol_candles[: idx + 1]
        dec = live_runner.process_closed_hourly_candle(
            symbol="SOLUSDT",
            recent_1h_candles=buffer_window,
            btc_daily_candles=btc_daily,
        )
        live_decisions.append(dec)

    # 3. Comparar longitud e igualdad campo por campo
    assert len(replay_decisions) == len(live_decisions)
    assert len(live_decisions) == 30

    for d_rep, d_live in zip(replay_decisions, live_decisions):
        ReplayHarness.assert_decisions_equal(d_live, d_rep)
