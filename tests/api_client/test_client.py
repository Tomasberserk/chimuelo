"""Tests para BinanceAuthenticatedClient (M2).

Cubre:
    - GET/POST/DELETE exitosos → retorna JSON.
    - 429 con Retry-After header → duerme max(Retry-After, backoff) y reintenta.
    - 429 agotando reintentos → RateLimitExceededError.
    - 5xx → backoff y reintenta; agotando reintentos → ExchangeUnreachableError.
    - 4xx (no 429) → BinanceAPIError sin reintento.
    - Timeout → ExchangeUnreachableError.
    - is_order=True → consume_order en vez de consume_weight.
    - sync_server_time → delega offset al signer.
    - _calc_backoff → exponential con jitter acotado a max_delay.
    - _raise_binance_error → BinanceAPIError con body malformado.

Mocks: `responses` para interceptar HTTP, `unittest.mock` para signer y rate_limiter.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import responses as responses_lib

from chimuelo_prime.api_client.client import BinanceAuthenticatedClient
from chimuelo_prime.api_client.exceptions import BinanceAPIError, RateLimitExceededError
from chimuelo_prime.api_client.models import RetryConfig
from chimuelo_prime.exchange_config.exceptions import ExchangeUnreachableError

BASE_URL = "https://testnet.binance.vision"
ENDPOINT = "/api/v3/account"
FULL_URL = f"{BASE_URL}{ENDPOINT}"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def mock_signer() -> MagicMock:
    signer = MagicMock()
    signer.api_key = "test_api_key_1234"
    signer.sign_params.side_effect = lambda p: {
        **p,
        "timestamp": 1_700_000_000_000,
        "signature": "fakesig",
    }
    return signer


@pytest.fixture()
def mock_rate_limiter() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def no_retry_config() -> RetryConfig:
    return RetryConfig(max_retries=0, base_delay_seconds=0.01, jitter_seconds=0.0)


@pytest.fixture()
def one_retry_config() -> RetryConfig:
    return RetryConfig(max_retries=1, base_delay_seconds=0.01, jitter_seconds=0.0)


@pytest.fixture()
def three_retry_config() -> RetryConfig:
    return RetryConfig(max_retries=3, base_delay_seconds=0.01, jitter_seconds=0.0)


def make_client(
    signer: MagicMock,
    rate_limiter: MagicMock,
    retry_config: RetryConfig | None = None,
) -> BinanceAuthenticatedClient:
    return BinanceAuthenticatedClient(
        base_url=BASE_URL,
        signer=signer,
        rate_limiter=rate_limiter,
        retry_config=retry_config,
        timeout=5,
    )


# --------------------------------------------------------------------------- #
# Requests exitosos
# --------------------------------------------------------------------------- #
class TestSuccessfulRequests:
    @responses_lib.activate
    def test_get_returns_json(self, mock_signer: MagicMock, mock_rate_limiter: MagicMock) -> None:
        responses_lib.add(responses_lib.GET, FULL_URL, json={"balances": []}, status=200)
        client = make_client(mock_signer, mock_rate_limiter)
        result = client.get(ENDPOINT)
        assert result == {"balances": []}

    @responses_lib.activate
    def test_post_returns_json(self, mock_signer: MagicMock, mock_rate_limiter: MagicMock) -> None:
        responses_lib.add(responses_lib.POST, FULL_URL, json={"orderId": 42}, status=200)
        client = make_client(mock_signer, mock_rate_limiter)
        result = client.post(ENDPOINT)
        assert result == {"orderId": 42}

    @responses_lib.activate
    def test_delete_returns_json(
        self, mock_signer: MagicMock, mock_rate_limiter: MagicMock
    ) -> None:
        responses_lib.add(responses_lib.DELETE, FULL_URL, json={"status": "CANCELED"}, status=200)
        client = make_client(mock_signer, mock_rate_limiter)
        result = client.delete(ENDPOINT)
        assert result == {"status": "CANCELED"}

    @responses_lib.activate
    def test_get_passes_weight_to_consume_weight(
        self, mock_signer: MagicMock, mock_rate_limiter: MagicMock
    ) -> None:
        responses_lib.add(responses_lib.GET, FULL_URL, json={}, status=200)
        client = make_client(mock_signer, mock_rate_limiter)
        client.get(ENDPOINT, weight=5)
        mock_rate_limiter.consume_weight.assert_called_once_with(5)

    @responses_lib.activate
    def test_post_with_is_order_calls_consume_order(
        self, mock_signer: MagicMock, mock_rate_limiter: MagicMock
    ) -> None:
        responses_lib.add(responses_lib.POST, FULL_URL, json={"orderId": 1}, status=200)
        client = make_client(mock_signer, mock_rate_limiter)
        client.post(ENDPOINT, weight=2, is_order=True)
        mock_rate_limiter.consume_order.assert_called_once_with(2)
        mock_rate_limiter.consume_weight.assert_not_called()

    @responses_lib.activate
    def test_apikey_header_sent(self, mock_signer: MagicMock, mock_rate_limiter: MagicMock) -> None:
        responses_lib.add(responses_lib.GET, FULL_URL, json={}, status=200)
        client = make_client(mock_signer, mock_rate_limiter)
        client.get(ENDPOINT)
        assert responses_lib.calls[0].request.headers["X-MBX-APIKEY"] == "test_api_key_1234"


# --------------------------------------------------------------------------- #
# 4xx — BinanceAPIError (sin reintento)
# --------------------------------------------------------------------------- #
class TestClientFourXX:
    @responses_lib.activate
    def test_400_raises_binance_api_error(
        self, mock_signer: MagicMock, mock_rate_limiter: MagicMock, no_retry_config: RetryConfig
    ) -> None:
        responses_lib.add(
            responses_lib.GET,
            FULL_URL,
            json={"code": -1121, "msg": "Invalid symbol."},
            status=400,
        )
        client = make_client(mock_signer, mock_rate_limiter, no_retry_config)
        with pytest.raises(BinanceAPIError) as exc_info:
            client.get(ENDPOINT)
        assert exc_info.value.status_code == 400
        assert exc_info.value.binance_code == -1121
        assert "Invalid symbol." in exc_info.value.msg

    @responses_lib.activate
    def test_401_raises_binance_api_error(
        self, mock_signer: MagicMock, mock_rate_limiter: MagicMock, no_retry_config: RetryConfig
    ) -> None:
        responses_lib.add(
            responses_lib.GET,
            FULL_URL,
            json={"code": -2014, "msg": "Invalid API-key format."},
            status=401,
        )
        client = make_client(mock_signer, mock_rate_limiter, no_retry_config)
        with pytest.raises(BinanceAPIError) as exc_info:
            client.get(ENDPOINT)
        assert exc_info.value.status_code == 401

    @responses_lib.activate
    def test_4xx_no_retry_only_one_call(
        self, mock_signer: MagicMock, mock_rate_limiter: MagicMock, three_retry_config: RetryConfig
    ) -> None:
        responses_lib.add(
            responses_lib.GET,
            FULL_URL,
            json={"code": -1121, "msg": "Invalid symbol."},
            status=400,
        )
        client = make_client(mock_signer, mock_rate_limiter, three_retry_config)
        with pytest.raises(BinanceAPIError):
            client.get(ENDPOINT)
        assert len(responses_lib.calls) == 1

    @responses_lib.activate
    def test_malformed_error_body_raises_binance_api_error(
        self, mock_signer: MagicMock, mock_rate_limiter: MagicMock, no_retry_config: RetryConfig
    ) -> None:
        responses_lib.add(
            responses_lib.GET,
            FULL_URL,
            body="Not JSON at all",
            status=400,
            content_type="text/plain",
        )
        client = make_client(mock_signer, mock_rate_limiter, no_retry_config)
        with pytest.raises(BinanceAPIError) as exc_info:
            client.get(ENDPOINT)
        assert exc_info.value.binance_code == -1


# --------------------------------------------------------------------------- #
# 429 — Rate limit con reintentos
# --------------------------------------------------------------------------- #
class TestClientRateLimit:
    @responses_lib.activate
    @patch("chimuelo_prime.api_client.client.time.sleep")
    def test_429_retries_and_succeeds(
        self,
        mock_sleep: MagicMock,
        mock_signer: MagicMock,
        mock_rate_limiter: MagicMock,
        one_retry_config: RetryConfig,
    ) -> None:
        responses_lib.add(responses_lib.GET, FULL_URL, status=429, headers={"Retry-After": "1"})
        responses_lib.add(responses_lib.GET, FULL_URL, json={"ok": True}, status=200)
        client = make_client(mock_signer, mock_rate_limiter, one_retry_config)
        result = client.get(ENDPOINT)
        assert result == {"ok": True}
        mock_sleep.assert_called_once()

    @responses_lib.activate
    @patch("chimuelo_prime.api_client.client.time.sleep")
    def test_429_respects_retry_after_header(
        self,
        mock_sleep: MagicMock,
        mock_signer: MagicMock,
        mock_rate_limiter: MagicMock,
        one_retry_config: RetryConfig,
    ) -> None:
        responses_lib.add(responses_lib.GET, FULL_URL, status=429, headers={"Retry-After": "30"})
        responses_lib.add(responses_lib.GET, FULL_URL, json={}, status=200)
        client = make_client(mock_signer, mock_rate_limiter, one_retry_config)
        client.get(ENDPOINT)
        sleep_arg = mock_sleep.call_args[0][0]
        assert sleep_arg >= 30.0

    @responses_lib.activate
    @patch("chimuelo_prime.api_client.client.time.sleep")
    def test_429_exhausted_raises_rate_limit_exceeded(
        self,
        mock_sleep: MagicMock,
        mock_signer: MagicMock,
        mock_rate_limiter: MagicMock,
        no_retry_config: RetryConfig,
    ) -> None:
        responses_lib.add(responses_lib.GET, FULL_URL, status=429)
        client = make_client(mock_signer, mock_rate_limiter, no_retry_config)
        with pytest.raises(RateLimitExceededError):
            client.get(ENDPOINT)

    @responses_lib.activate
    @patch("chimuelo_prime.api_client.client.time.sleep")
    def test_429_retries_count(
        self,
        mock_sleep: MagicMock,
        mock_signer: MagicMock,
        mock_rate_limiter: MagicMock,
    ) -> None:
        retry_cfg = RetryConfig(max_retries=2, base_delay_seconds=0.01, jitter_seconds=0.0)
        for _ in range(3):  # 1 inicial + 2 reintentos = 3 llamadas totales
            responses_lib.add(responses_lib.GET, FULL_URL, status=429)
        client = make_client(mock_signer, mock_rate_limiter, retry_cfg)
        with pytest.raises(RateLimitExceededError):
            client.get(ENDPOINT)
        assert len(responses_lib.calls) == 3


# --------------------------------------------------------------------------- #
# 5xx — Server error con reintentos
# --------------------------------------------------------------------------- #
class TestClientServerErrors:
    @responses_lib.activate
    @patch("chimuelo_prime.api_client.client.time.sleep")
    def test_500_retries_and_succeeds(
        self,
        mock_sleep: MagicMock,
        mock_signer: MagicMock,
        mock_rate_limiter: MagicMock,
        one_retry_config: RetryConfig,
    ) -> None:
        responses_lib.add(responses_lib.GET, FULL_URL, status=500)
        responses_lib.add(responses_lib.GET, FULL_URL, json={"data": "ok"}, status=200)
        client = make_client(mock_signer, mock_rate_limiter, one_retry_config)
        result = client.get(ENDPOINT)
        assert result == {"data": "ok"}

    @responses_lib.activate
    @patch("chimuelo_prime.api_client.client.time.sleep")
    def test_503_exhausted_raises_exchange_unreachable(
        self,
        mock_sleep: MagicMock,
        mock_signer: MagicMock,
        mock_rate_limiter: MagicMock,
        no_retry_config: RetryConfig,
    ) -> None:
        responses_lib.add(responses_lib.GET, FULL_URL, status=503)
        client = make_client(mock_signer, mock_rate_limiter, no_retry_config)
        with pytest.raises(ExchangeUnreachableError):
            client.get(ENDPOINT)

    @responses_lib.activate
    @patch("chimuelo_prime.api_client.client.time.sleep")
    def test_502_retries_count(
        self,
        mock_sleep: MagicMock,
        mock_signer: MagicMock,
        mock_rate_limiter: MagicMock,
    ) -> None:
        retry_cfg = RetryConfig(max_retries=2, base_delay_seconds=0.01, jitter_seconds=0.0)
        for _ in range(3):
            responses_lib.add(responses_lib.GET, FULL_URL, status=502)
        client = make_client(mock_signer, mock_rate_limiter, retry_cfg)
        with pytest.raises(ExchangeUnreachableError):
            client.get(ENDPOINT)
        assert len(responses_lib.calls) == 3


# --------------------------------------------------------------------------- #
# Timeout y errores de red
# --------------------------------------------------------------------------- #
class TestClientNetworkErrors:
    @responses_lib.activate
    def test_timeout_raises_exchange_unreachable(
        self, mock_signer: MagicMock, mock_rate_limiter: MagicMock, no_retry_config: RetryConfig
    ) -> None:
        import requests.exceptions as req_exc

        responses_lib.add(responses_lib.GET, FULL_URL, body=req_exc.Timeout())
        client = make_client(mock_signer, mock_rate_limiter, no_retry_config)
        with pytest.raises(ExchangeUnreachableError, match="Timeout"):
            client.get(ENDPOINT)

    @responses_lib.activate
    def test_connection_error_raises_exchange_unreachable(
        self, mock_signer: MagicMock, mock_rate_limiter: MagicMock, no_retry_config: RetryConfig
    ) -> None:
        import requests.exceptions as req_exc

        responses_lib.add(responses_lib.GET, FULL_URL, body=req_exc.ConnectionError())
        client = make_client(mock_signer, mock_rate_limiter, no_retry_config)
        with pytest.raises(ExchangeUnreachableError):
            client.get(ENDPOINT)


# --------------------------------------------------------------------------- #
# sync_server_time y close
# --------------------------------------------------------------------------- #
class TestClientUtilities:
    @patch("chimuelo_prime.api_client.client.time.time", return_value=1_700_000_000.0)
    def test_sync_server_time_sets_offset(
        self, _mock_time: MagicMock, mock_signer: MagicMock, mock_rate_limiter: MagicMock
    ) -> None:
        client = make_client(mock_signer, mock_rate_limiter)
        server_time_ms = 1_700_000_001_000  # 1 segundo adelantado
        client.sync_server_time(server_time_ms)
        mock_signer.set_server_time_offset.assert_called_once_with(1000)

    def test_close_does_not_raise(
        self, mock_signer: MagicMock, mock_rate_limiter: MagicMock
    ) -> None:
        client = make_client(mock_signer, mock_rate_limiter)
        client.close()  # no debe lanzar


# --------------------------------------------------------------------------- #
# _calc_backoff
# --------------------------------------------------------------------------- #
class TestCalcBackoff:
    def test_attempt_zero_is_base_delay(
        self, mock_signer: MagicMock, mock_rate_limiter: MagicMock
    ) -> None:
        cfg = RetryConfig(
            max_retries=3, base_delay_seconds=1.0, max_delay_seconds=60.0, jitter_seconds=0.0
        )
        client = make_client(mock_signer, mock_rate_limiter, cfg)
        assert client._calc_backoff(0) == pytest.approx(1.0, abs=1e-9)

    def test_attempt_one_doubles(
        self, mock_signer: MagicMock, mock_rate_limiter: MagicMock
    ) -> None:
        cfg = RetryConfig(
            max_retries=3, base_delay_seconds=1.0, max_delay_seconds=60.0, jitter_seconds=0.0
        )
        client = make_client(mock_signer, mock_rate_limiter, cfg)
        assert client._calc_backoff(1) == pytest.approx(2.0, abs=1e-9)

    def test_capped_at_max_delay(
        self, mock_signer: MagicMock, mock_rate_limiter: MagicMock
    ) -> None:
        cfg = RetryConfig(
            max_retries=3, base_delay_seconds=1.0, max_delay_seconds=5.0, jitter_seconds=0.0
        )
        client = make_client(mock_signer, mock_rate_limiter, cfg)
        # 1.0 * 2^10 = 1024 >> 5.0
        assert client._calc_backoff(10) == pytest.approx(5.0, abs=1e-9)

    def test_jitter_adds_non_negative_amount(
        self, mock_signer: MagicMock, mock_rate_limiter: MagicMock
    ) -> None:
        cfg = RetryConfig(
            max_retries=3, base_delay_seconds=1.0, max_delay_seconds=60.0, jitter_seconds=0.5
        )
        client = make_client(mock_signer, mock_rate_limiter, cfg)
        result = client._calc_backoff(0)
        assert result >= 1.0
        assert result <= 1.5
