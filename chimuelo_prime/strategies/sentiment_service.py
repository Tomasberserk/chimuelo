"""Servicio de Inteligencia de Sentimiento Cualitativo y Macroeconómico (M10).

Responsabilidades:
    - Conexión a la API pública de Alternative.me Crypto Fear & Greed Index.
    - Caché en memoria con TTL configurable para mitigar latencia y rate limits.
    - Fallback resiliente y modo degradado seguro (offline) en caso de fallos de red o errores HTTP.
    - Dictamen de regímenes macro (RISK_ON, NEUTRAL, RISK_OFF, BLACK_SWAN_VETO).
    - Autorización o veto de operaciones largas (can_open_longs).
    - Tipado estricto, precisión Decimal pura y observabilidad vía structlog.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal

import requests

from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.strategies.sentiment_models import (
    MacroRegime,
    MarketSentimentReport,
    SentimentCategory,
)


class MacroSentimentService:
    """Servicio de análisis y gestión de régimen de sentimiento macroeconómico."""

    DEFAULT_API_URL = "https://api.alternative.me/fng/?limit=7"
    DEFAULT_CACHE_TTL_SECONDS = 3600.0
    DEFAULT_TIMEOUT_SECONDS = 5.0
    DEFAULT_BLACK_SWAN_THRESHOLD = Decimal("20.0")
    DEFAULT_FALLBACK_SCORE = Decimal("50.0")

    def __init__(
        self,
        api_url: str = DEFAULT_API_URL,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        black_swan_threshold: Decimal = DEFAULT_BLACK_SWAN_THRESHOLD,
        default_fallback_score: Decimal = DEFAULT_FALLBACK_SCORE,
        session: requests.Session | None = None,
        use_stale_cache_on_error: bool = True,
    ) -> None:
        self._api_url = api_url
        self._cache_ttl = cache_ttl_seconds
        self._timeout = timeout
        self._black_swan_threshold = black_swan_threshold
        self._default_fallback_score = default_fallback_score
        self._session = session or requests.Session()
        self._owns_session = session is None
        self._use_stale_cache_on_error = use_stale_cache_on_error

        self._cached_report: MarketSentimentReport | None = None
        self._cached_history: list[MarketSentimentReport] = []
        self._last_fetch_time: float = 0.0
        self._log = get_logger(__name__)

    @property
    def api_url(self) -> str:
        return self._api_url

    @property
    def cache_ttl_seconds(self) -> float:
        return self._cache_ttl

    @property
    def black_swan_threshold(self) -> Decimal:
        return self._black_swan_threshold

    def get_sentiment_report(self, force_refresh: bool = False) -> MarketSentimentReport:
        """Obtiene el reporte consolidado de sentimiento de mercado más reciente.

        Usa caché en memoria si la entrada no ha expirado y no se solicita refresco forzado.
        Si la llamada a la API falla, activa el modo fallback seguro o reutiliza la última caché válida.
        """
        now = time.time()
        if (
            not force_refresh
            and self._cached_report is not None
            and (now - self._last_fetch_time) < self._cache_ttl
        ):
            return self._cached_report

        try:
            reports = self._fetch_from_api()
            if reports:
                self._cached_report = reports[0]
                self._cached_history = reports
                self._last_fetch_time = now
                self._log.info(
                    "sentiment.fetch_success",
                    score=str(self._cached_report.score),
                    category=self._cached_report.category.value,
                    regime=self._cached_report.macro_regime.value,
                    can_open_longs=self._cached_report.can_open_longs,
                )
                return self._cached_report
        except Exception as exc:
            self._log.warning(
                "sentiment.fetch_failed",
                error=str(exc),
                api_url=self._api_url,
                using_fallback=True,
            )

        # Manejo de fallback resiliente
        if self._use_stale_cache_on_error and self._cached_report is not None:
            self._log.info(
                "sentiment.using_stale_cache",
                score=str(self._cached_report.score),
                cached_time=self._last_fetch_time,
            )
            return self._cached_report

        fallback_report = self._build_fallback_report()
        self._cached_report = fallback_report
        self._last_fetch_time = now
        return fallback_report

    def can_open_longs(self) -> bool:
        """Indica si las condiciones macroeconómicas autorizan compras."""
        return self.get_sentiment_report().can_open_longs

    def get_latest_score(self) -> Decimal:
        """Retorna la puntuación numérica actual del Fear & Greed Index."""
        return self.get_sentiment_report().score

    def get_current_regime(self) -> MacroRegime:
        """Retorna el régimen macroeconómico actual."""
        return self.get_sentiment_report().macro_regime

    def get_historical_sentiment(self, limit: int = 7) -> list[MarketSentimentReport]:
        """Retorna la serie histórica de reportes obtenida en la última consulta."""
        self.get_sentiment_report()
        return self._cached_history[:limit]

    def _fetch_from_api(self) -> list[MarketSentimentReport]:
        """Realiza la petición HTTP a la API y parsea el payload JSON."""
        response = self._session.get(self._api_url, timeout=self._timeout)
        if response.status_code != 200:
            raise requests.HTTPError(
                f"Error en API Alternative.me: HTTP {response.status_code}",
                response=response,
            )

        data = response.json()
        if not isinstance(data, dict) or "data" not in data or not isinstance(data["data"], list):
            raise ValueError(f"Formato de respuesta inesperado de Alternative.me: {data!r}")

        items = data["data"]
        if not items:
            raise ValueError("Respuesta de Alternative.me no contiene elementos en 'data'")

        reports: list[MarketSentimentReport] = []
        for item in items:
            raw_value = item.get("value")
            if raw_value is None:
                continue

            # Conversión segura y estricta a Decimal
            score = Decimal(str(raw_value))
            # Normalizar límites 0-100 defensivamente
            score = max(Decimal("0.0"), min(Decimal("100.0"), score))

            raw_ts = item.get("timestamp")
            if raw_ts:
                try:
                    ts = datetime.fromtimestamp(int(raw_ts), tz=UTC)
                except Exception:
                    ts = datetime.now(UTC)
            else:
                ts = datetime.now(UTC)

            category = self._classify_category(score)
            regime, can_open_longs, veto_reason, summary = self._evaluate_regime(
                score=score, category=category
            )

            report = MarketSentimentReport(
                score=score,
                category=category,
                macro_regime=regime,
                can_open_longs=can_open_longs,
                veto_reason=veto_reason,
                source="Alternative.me Fear & Greed API",
                timestamp=ts,
                macro_summary=summary,
            )
            reports.append(report)

        if not reports:
            raise ValueError("No se pudieron parsear reportes válidos del payload")

        return reports

    def _classify_category(self, score: Decimal) -> SentimentCategory:
        """Clasifica el score en la categoría estándar de Alternative.me."""
        if score <= Decimal("24.0"):
            return SentimentCategory.EXTREME_FEAR
        elif score <= Decimal("44.0"):
            return SentimentCategory.FEAR
        elif score <= Decimal("55.0"):
            return SentimentCategory.NEUTRAL
        elif score <= Decimal("75.0"):
            return SentimentCategory.GREED
        else:
            return SentimentCategory.EXTREME_GREED

    def _evaluate_regime(
        self, score: Decimal, category: SentimentCategory
    ) -> tuple[MacroRegime, bool, str | None, str]:
        """Evalúa el régimen macroeconómico y determina la política de compras."""
        if score < self._black_swan_threshold:
            regime = MacroRegime.BLACK_SWAN_VETO
            can_longs = False
            veto = (
                f"Veto macroeconómico: Pánico extremo en mercado crypto "
                f"(Fear & Greed score {score:.1f} < {self._black_swan_threshold:.1f})"
            )
            summary = (
                f"Pánico extremo ({category.value}, Score {score:.1f}/100). "
                f"Nuevas compras bloqueadas por política de protección de capital."
            )
        elif score < Decimal("45.0"):
            regime = MacroRegime.RISK_OFF
            can_longs = True
            veto = None
            summary = (
                f"Régimen Risk-Off ({category.value}, Score {score:.1f}/100). "
                f"Mercado cauteloso; operaciones sujetas a filtros técnicos estrictos."
            )
        elif score <= Decimal("55.0"):
            regime = MacroRegime.NEUTRAL
            can_longs = True
            veto = None
            summary = (
                f"Régimen Neutral ({category.value}, Score {score:.1f}/100). "
                f"Mercado balanceado; operación cuantitativa normal."
            )
        else:
            regime = MacroRegime.RISK_ON
            can_longs = True
            veto = None
            summary = (
                f"Régimen Risk-On ({category.value}, Score {score:.1f}/100). "
                f"Apetito por riesgo favorable para estrategias tendenciales y reversión."
            )

        return regime, can_longs, veto, summary

    def _build_fallback_report(self) -> MarketSentimentReport:
        """Genera un reporte de sentimiento en modo degradado seguro."""
        score = self._default_fallback_score
        category = self._classify_category(score)
        regime, can_longs, veto, _ = self._evaluate_regime(score, category)

        return MarketSentimentReport(
            score=score,
            category=category,
            macro_regime=regime,
            can_open_longs=can_longs,
            veto_reason=veto,
            source="Offline Fallback Mode (Degraded)",
            timestamp=datetime.now(UTC),
            macro_summary=(
                "Modo degradado offline: API de sentimiento no disponible. "
                "Sentimiento macro neutral asumido por continuidad operativa."
            ),
        )

    def close(self) -> None:
        """Libera los recursos de conexión de la sesión HTTP si fue creada internamente."""
        if self._owns_session:
            self._session.close()
