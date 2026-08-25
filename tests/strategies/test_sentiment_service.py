"""Tests unitarios para MacroSentimentService (M10) e integración con RSIDivergenceStrategy."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import requests
from pydantic import ValidationError

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.strategies.models import SignalType
from chimuelo_prime.strategies.rsi_divergence import RSIDivergenceStrategy
from chimuelo_prime.strategies.sentiment_models import (
    MacroRegime,
    MarketSentimentReport,
    SentimentCategory,
)
from chimuelo_prime.strategies.sentiment_service import MacroSentimentService


def _create_mock_alternative_me_payload(
    values: list[tuple[str, str, int]] | None = None,
) -> dict:
    """Genera un payload simulado idéntico a la API de Alternative.me Crypto Fear & Greed."""
    if values is None:
        values = [
            ("25", "Fear", 1716076800),
            ("18", "Extreme Fear", 1715990400),
            ("50", "Neutral", 1715904000),
            ("65", "Greed", 1715817600),
            ("80", "Extreme Greed", 1715731200),
            ("10", "Extreme Fear", 1715644800),
            ("40", "Fear", 1715558400),
        ]
    data = [
        {
            "value": val,
            "value_classification": cls_name,
            "timestamp": str(ts),
            "time_until_update": "43200",
        }
        for val, cls_name, ts in values
    ]
    return {
        "name": "Fear and Greed Index",
        "data": data,
        "metadata": {"error": None},
    }


def _create_synthetic_candles_for_divergence() -> list[HistoricalCandle]:
    """Genera velas sintéticas que cumplen el patrón técnico de divergencia alcista."""
    candles: list[HistoricalCandle] = []
    base_time = datetime(2024, 1, 1, 0, 0)
    price = Decimal("100.0")

    # 1. Fase de tendencia inicial (210 velas)
    for i in range(210):
        dt = base_time + timedelta(hours=i)
        price += Decimal("0.5")
        candles.append(
            HistoricalCandle(
                timestamp=dt,
                open=price,
                high=price + Decimal("1.0"),
                low=price - Decimal("0.5"),
                close=price + Decimal("0.4"),
                volume=Decimal("1000.0"),
            )
        )

    # 2. Caída abrupta para generar sobreventa en RSI
    for i in range(5):
        dt = base_time + timedelta(hours=len(candles))
        price -= Decimal("4.0")
        candles.append(
            HistoricalCandle(
                timestamp=dt,
                open=price + Decimal("2.0"),
                high=price + Decimal("2.5"),
                low=price - Decimal("1.0"),
                close=price,
                volume=Decimal("2000.0"),
            )
        )

    # 3. Rebote intermedio
    for _ in range(6):
        dt = base_time + timedelta(hours=len(candles))
        price += Decimal("1.5")
        candles.append(
            HistoricalCandle(
                timestamp=dt,
                open=price - Decimal("0.5"),
                high=price + Decimal("0.5"),
                low=price - Decimal("0.5"),
                close=price,
                volume=Decimal("1500.0"),
            )
        )

    # 4. Segundo mínimo (divergencia)
    for _ in range(4):
        dt = base_time + timedelta(hours=len(candles))
        price -= Decimal("1.5")
        candles.append(
            HistoricalCandle(
                timestamp=dt,
                open=price + Decimal("0.5"),
                high=price + Decimal("0.5"),
                low=price - Decimal("0.5"),
                close=price,
                volume=Decimal("1500.0"),
            )
        )

    # 5. Vela de confirmación
    dt = base_time + timedelta(hours=len(candles))
    candles.append(
        HistoricalCandle(
            timestamp=dt,
            open=price,
            high=price + Decimal("6.0"),
            low=price - Decimal("0.2"),
            close=price + Decimal("5.5"),
            volume=Decimal("3000.0"),
        )
    )
    return candles


# ============================================================================ #
# 1. Tests de Inicialización y Configuración
# ============================================================================ #


class TestMacroSentimentServiceInit:
    """Pruebas de inicialización, defaults y propiedades de MacroSentimentService."""

    def test_default_initialization(self) -> None:
        service = MacroSentimentService()
        assert service.api_url == "https://api.alternative.me/fng/?limit=7"
        assert service.cache_ttl_seconds == 3600.0
        assert service.black_swan_threshold == Decimal("20.0")
        assert service._timeout == 5.0
        assert service._default_fallback_score == Decimal("50.0")
        assert service._use_stale_cache_on_error is True
        service.close()

    def test_custom_parameters(self) -> None:
        custom_session = requests.Session()
        service = MacroSentimentService(
            api_url="https://custom-api.example.com/fng",
            cache_ttl_seconds=120.0,
            timeout=10.0,
            black_swan_threshold=Decimal("25.0"),
            default_fallback_score=Decimal("45.0"),
            session=custom_session,
            use_stale_cache_on_error=False,
        )
        assert service.api_url == "https://custom-api.example.com/fng"
        assert service.cache_ttl_seconds == 120.0
        assert service._timeout == 10.0
        assert service.black_swan_threshold == Decimal("25.0")
        assert service._default_fallback_score == Decimal("45.0")
        assert service._session is custom_session
        assert service._use_stale_cache_on_error is False
        service.close()
        custom_session.close()


# ============================================================================ #
# 2. Tests de Petición HTTP y Parseo de Alternative.me API
# ============================================================================ #


class TestMacroSentimentServiceAPIParsing:
    """Pruebas de parseo de JSON, conversión a Decimal y categorización."""

    def test_successful_api_fetch_and_history(self) -> None:
        mock_payload = _create_mock_alternative_me_payload()
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_payload

        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.return_value = mock_response

        service = MacroSentimentService(session=mock_session)
        report = service.get_sentiment_report()

        assert isinstance(report, MarketSentimentReport)
        assert report.score == Decimal("25")
        assert report.category == SentimentCategory.FEAR
        assert report.macro_regime == MacroRegime.RISK_OFF
        assert report.can_open_longs is True
        assert report.veto_reason is None
        assert "Alternative.me" in report.source
        assert isinstance(report.timestamp, datetime)

        # Historial de 7 reportes
        history = service.get_historical_sentiment(limit=7)
        assert len(history) == 7
        assert all(isinstance(h.score, Decimal) for h in history)
        assert history[0].score == Decimal("25")
        assert history[1].score == Decimal("18")
        assert history[1].category == SentimentCategory.EXTREME_FEAR
        assert history[1].macro_regime == MacroRegime.BLACK_SWAN_VETO
        assert history[1].can_open_longs is False

    @pytest.mark.parametrize(
        ("raw_score", "expected_category", "expected_regime", "expected_can_longs"),
        [
            ("10", SentimentCategory.EXTREME_FEAR, MacroRegime.BLACK_SWAN_VETO, False),
            ("19.9", SentimentCategory.EXTREME_FEAR, MacroRegime.BLACK_SWAN_VETO, False),
            ("20.0", SentimentCategory.EXTREME_FEAR, MacroRegime.RISK_OFF, True),
            ("24.0", SentimentCategory.EXTREME_FEAR, MacroRegime.RISK_OFF, True),
            ("25.0", SentimentCategory.FEAR, MacroRegime.RISK_OFF, True),
            ("44.0", SentimentCategory.FEAR, MacroRegime.RISK_OFF, True),
            ("45.0", SentimentCategory.NEUTRAL, MacroRegime.NEUTRAL, True),
            ("50.0", SentimentCategory.NEUTRAL, MacroRegime.NEUTRAL, True),
            ("55.0", SentimentCategory.NEUTRAL, MacroRegime.NEUTRAL, True),
            ("56.0", SentimentCategory.GREED, MacroRegime.RISK_ON, True),
            ("75.0", SentimentCategory.GREED, MacroRegime.RISK_ON, True),
            ("76.0", SentimentCategory.EXTREME_GREED, MacroRegime.RISK_ON, True),
            ("95.0", SentimentCategory.EXTREME_GREED, MacroRegime.RISK_ON, True),
        ],
    )
    def test_sentiment_score_boundaries_and_regimes(
        self,
        raw_score: str,
        expected_category: SentimentCategory,
        expected_regime: MacroRegime,
        expected_can_longs: bool,
    ) -> None:
        payload = _create_mock_alternative_me_payload([(raw_score, "Mock", 1716076800)])
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = payload

        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.return_value = mock_response

        service = MacroSentimentService(session=mock_session)
        report = service.get_sentiment_report()

        assert report.score == Decimal(raw_score)
        assert report.category == expected_category
        assert report.macro_regime == expected_regime
        assert report.can_open_longs is expected_can_longs
        if not expected_can_longs:
            assert report.veto_reason is not None
            assert "Veto macroeconómico" in report.veto_reason

    def test_custom_black_swan_threshold_veto(self) -> None:
        payload = _create_mock_alternative_me_payload([("28", "Fear", 1716076800)])
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = payload

        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.return_value = mock_response

        # Umbral configurado en 30.0 -> Score 28 debe ser vetado
        service = MacroSentimentService(
            black_swan_threshold=Decimal("30.0"), session=mock_session
        )
        report = service.get_sentiment_report()

        assert report.score == Decimal("28")
        assert report.category == SentimentCategory.FEAR
        assert report.macro_regime == MacroRegime.BLACK_SWAN_VETO
        assert report.can_open_longs is False
        assert report.veto_reason is not None

    def test_score_clamping_defense(self) -> None:
        """Verifica que valores anómalos (<0 o >100) sean acotados defensivamente."""
        payload = _create_mock_alternative_me_payload([("150", "Extreme Greed", 1716076800)])
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = payload

        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.return_value = mock_response

        service = MacroSentimentService(session=mock_session)
        report = service.get_sentiment_report()
        assert report.score == Decimal("100.0")
        assert report.category == SentimentCategory.EXTREME_GREED


# ============================================================================ #
# 3. Tests de Caché en Memoria y Refresco Forzado
# ============================================================================ #


class TestMacroSentimentServiceCaching:
    """Pruebas del sistema de caché in-memory con TTL."""

    def test_in_memory_cache_avoids_redundant_http_calls(self) -> None:
        payload = _create_mock_alternative_me_payload([("60", "Greed", 1716076800)])
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = payload

        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.return_value = mock_response

        service = MacroSentimentService(cache_ttl_seconds=300.0, session=mock_session)

        # Primer llamado: realiza petición HTTP
        rep1 = service.get_sentiment_report()
        assert mock_session.get.call_count == 1
        assert rep1.score == Decimal("60")

        # Segundo llamado inmediato: retorna caché
        rep2 = service.get_sentiment_report()
        assert mock_session.get.call_count == 1
        assert rep2 is rep1

        # Tercer llamado: helper methods usan caché
        assert service.can_open_longs() is True
        assert service.get_latest_score() == Decimal("60")
        assert service.get_current_regime() == MacroRegime.RISK_ON
        assert mock_session.get.call_count == 1

    def test_force_refresh_bypasses_cache(self) -> None:
        payload1 = _create_mock_alternative_me_payload([("60", "Greed", 1716076800)])
        payload2 = _create_mock_alternative_me_payload([("70", "Greed", 1716076800)])

        mock_response1 = MagicMock(spec=requests.Response)
        mock_response1.status_code = 200
        mock_response1.json.return_value = payload1

        mock_response2 = MagicMock(spec=requests.Response)
        mock_response2.status_code = 200
        mock_response2.json.return_value = payload2

        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.side_effect = [mock_response1, mock_response2]

        service = MacroSentimentService(cache_ttl_seconds=300.0, session=mock_session)

        rep1 = service.get_sentiment_report()
        assert rep1.score == Decimal("60")
        assert mock_session.get.call_count == 1

        # force_refresh = True
        rep2 = service.get_sentiment_report(force_refresh=True)
        assert rep2.score == Decimal("70")
        assert mock_session.get.call_count == 2

    def test_cache_expiration_triggers_new_fetch(self) -> None:
        payload = _create_mock_alternative_me_payload([("55", "Neutral", 1716076800)])
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = payload

        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.return_value = mock_response

        # TTL muy corto de 0.05 segundos
        service = MacroSentimentService(cache_ttl_seconds=0.05, session=mock_session)

        service.get_sentiment_report()
        assert mock_session.get.call_count == 1

        # Esperar a que expire la caché
        time.sleep(0.06)

        service.get_sentiment_report()
        assert mock_session.get.call_count == 2


# ============================================================================ #
# 4. Tests de Resiliencia, Fallback y Modo Degradado Seguro
# ============================================================================ #


class TestMacroSentimentServiceFallback:
    """Pruebas de tolerancia a fallos de red, timeouts y payloads malformados."""

    def test_network_timeout_fallback(self) -> None:
        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.side_effect = requests.exceptions.Timeout("Connection timed out")

        service = MacroSentimentService(session=mock_session)
        report = service.get_sentiment_report()

        assert isinstance(report, MarketSentimentReport)
        assert report.score == Decimal("50.0")
        assert report.category == SentimentCategory.NEUTRAL
        assert report.macro_regime == MacroRegime.NEUTRAL
        assert report.can_open_longs is True
        assert "Offline Fallback" in report.source

    def test_connection_error_fallback(self) -> None:
        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.side_effect = requests.exceptions.ConnectionError("DNS resolution failed")

        service = MacroSentimentService(session=mock_session)
        report = service.get_sentiment_report()

        assert report.score == Decimal("50.0")
        assert report.can_open_longs is True

    def test_http_server_error_fallback(self) -> None:
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 500
        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.return_value = mock_response

        service = MacroSentimentService(session=mock_session)
        report = service.get_sentiment_report()

        assert report.score == Decimal("50.0")
        assert report.can_open_longs is True

    def test_malformed_json_fallback(self) -> None:
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"invalid_structure": 123}
        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.return_value = mock_response

        service = MacroSentimentService(session=mock_session)
        report = service.get_sentiment_report()

        assert report.score == Decimal("50.0")
        assert report.can_open_longs is True

    def test_empty_data_list_fallback(self) -> None:
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}
        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.return_value = mock_response

        service = MacroSentimentService(session=mock_session)
        report = service.get_sentiment_report()

        assert report.score == Decimal("50.0")
        assert report.can_open_longs is True

    def test_stale_cache_used_when_api_fails_subsequently(self) -> None:
        """Si la API falla pero existía una caché previa, sirve la caché previa."""
        valid_payload = _create_mock_alternative_me_payload([("72", "Greed", 1716076800)])
        valid_resp = MagicMock(spec=requests.Response)
        valid_resp.status_code = 200
        valid_resp.json.return_value = valid_payload

        mock_session = MagicMock(spec=requests.Session)
        # Primer llamado OK, segundo llamado Timeout
        mock_session.get.side_effect = [
            valid_resp,
            requests.exceptions.Timeout("API timeout on refresh"),
        ]

        service = MacroSentimentService(
            cache_ttl_seconds=0.01, session=mock_session, use_stale_cache_on_error=True
        )

        rep1 = service.get_sentiment_report()
        assert rep1.score == Decimal("72")

        time.sleep(0.02)  # Expira TTL

        # Segundo llamado: falla el fetch pero retorna stale cache (score 72)
        rep2 = service.get_sentiment_report()
        assert rep2.score == Decimal("72")
        assert rep2.category == SentimentCategory.GREED


# ============================================================================ #
# 5. Tests de Pureza Decimal y Validación Pydantic
# ============================================================================ #


class TestSentimentModelsPurity:
    """Valida que los modelos de sentimiento rechacen floats y sean inmutables."""

    def test_market_sentiment_report_rejects_floats(self) -> None:
        with pytest.raises(TypeError, match="Floats no permitidos"):
            MarketSentimentReport(
                score=50.5,  # float prohibido
                category=SentimentCategory.NEUTRAL,
                macro_regime=MacroRegime.NEUTRAL,
                can_open_longs=True,
            )

    def test_market_sentiment_report_is_frozen(self) -> None:
        report = MarketSentimentReport(
            score=Decimal("50.0"),
            category=SentimentCategory.NEUTRAL,
            macro_regime=MacroRegime.NEUTRAL,
            can_open_longs=True,
        )
        with pytest.raises(ValidationError):
            report.can_open_longs = False  # type: ignore[misc]

    def test_market_sentiment_report_score_string_coercion(self) -> None:
        report = MarketSentimentReport(
            score="65",  # String numérico se convierte a Decimal de forma segura
            category=SentimentCategory.GREED,
            macro_regime=MacroRegime.RISK_ON,
            can_open_longs=True,
        )
        assert isinstance(report.score, Decimal)
        assert report.score == Decimal("65")


# ============================================================================ #
# 6. Tests de Integración con RSIDivergenceStrategy
# ============================================================================ #


class TestRSIDivergenceSentimentIntegration:
    """Pruebas de filtrado Macro Sentiment en la generación de señales BUY."""

    def test_buy_signal_allowed_when_can_open_longs_is_true(self) -> None:
        candles = _create_synthetic_candles_for_divergence()
        eval_idx = len(candles) - 1

        # Sentiment Service con score 60 (Greed, Risk-On, can_open_longs=True)
        payload = _create_mock_alternative_me_payload([("60", "Greed", 1716076800)])
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = payload

        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.return_value = mock_response

        sentiment_service = MacroSentimentService(session=mock_session)

        strategy = RSIDivergenceStrategy(
            symbol="SOLUSDT",
            rsi_period=14,
            rsi_oversold_threshold=Decimal("45.0"),
            ema_trend_period=50,
            lookback_bars=30,
            macro_sentiment_service=sentiment_service,
        )

        strategy.prepare_indicators(candles)
        signal = strategy.evaluate_candle(candles, eval_idx)

        assert signal is not None
        assert signal.signal_type == SignalType.BUY
        assert signal.metadata is not None
        assert signal.metadata.get("macro_sentiment_score") == "60"
        assert signal.metadata.get("macro_sentiment_regime") == MacroRegime.RISK_ON.value
        assert signal.metadata.get("macro_sentiment_category") == SentimentCategory.GREED.value

    def test_buy_signal_vetoed_when_can_open_longs_is_false(self) -> None:
        candles = _create_synthetic_candles_for_divergence()
        eval_idx = len(candles) - 1

        # Sentiment Service con score 10 (Extreme Fear / Black Swan -> can_open_longs=False)
        payload = _create_mock_alternative_me_payload([("10", "Extreme Fear", 1716076800)])
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = payload

        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.return_value = mock_response

        sentiment_service = MacroSentimentService(
            black_swan_threshold=Decimal("20.0"), session=mock_session
        )

        strategy = RSIDivergenceStrategy(
            symbol="SOLUSDT",
            rsi_period=14,
            rsi_oversold_threshold=Decimal("45.0"),
            ema_trend_period=50,
            lookback_bars=30,
            macro_sentiment_service=sentiment_service,
        )

        strategy.prepare_indicators(candles)
        signal = strategy.evaluate_candle(candles, eval_idx)

        # Debe ser bloqueada (None) debido al veto macro
        assert signal is None

    def test_strategy_without_sentiment_service_operates_normally(self) -> None:
        candles = _create_synthetic_candles_for_divergence()
        eval_idx = len(candles) - 1

        strategy = RSIDivergenceStrategy(
            symbol="SOLUSDT",
            rsi_period=14,
            rsi_oversold_threshold=Decimal("45.0"),
            ema_trend_period=50,
            lookback_bars=30,
            macro_sentiment_service=None,
        )

        strategy.prepare_indicators(candles)
        signal = strategy.evaluate_candle(candles, eval_idx)

        assert signal is not None
        assert signal.signal_type == SignalType.BUY
        assert "macro_sentiment_score" not in signal.metadata

    def test_dynamic_sentiment_service_injection_via_setter(self) -> None:
        candles = _create_synthetic_candles_for_divergence()
        eval_idx = len(candles) - 1

        strategy = RSIDivergenceStrategy(
            symbol="SOLUSDT",
            rsi_oversold_threshold=Decimal("45.0"),
            ema_trend_period=50,
            lookback_bars=30,
        )
        assert strategy.macro_sentiment_service is None

        # Inyectar servicio con veto
        payload = _create_mock_alternative_me_payload([("12", "Extreme Fear", 1716076800)])
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = payload
        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.return_value = mock_response

        veto_service = MacroSentimentService(session=mock_session)
        strategy.macro_sentiment_service = veto_service

        strategy.prepare_indicators(candles)
        assert strategy.evaluate_candle(candles, eval_idx) is None
