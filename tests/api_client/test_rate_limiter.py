"""Tests para TokenBucket y RateLimiter (M2).

Cubre:
    - TokenBucket: consume exitoso, retorna wait > 0 cuando no hay tokens,
      recarga tras interval, available_tokens.
    - RateLimiter: consume_weight delega al weight bucket,
      consume_order delega a ambos buckets.
    - Thread-safety: consumo concurrente no produce tokens negativos.

Estrategia de tiempo:
    Se usa freezegun para controlar time.monotonic() en el contexto de TokenBucket.
    Donde freezegun no aplica directamente, se manipula _last_refill manualmente.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

from chimuelo_prime.api_client.models import RateLimitConfig
from chimuelo_prime.api_client.rate_limiter import RateLimiter, TokenBucket


# --------------------------------------------------------------------------- #
# TokenBucket — lógica básica
# --------------------------------------------------------------------------- #
class TestTokenBucketConsume:
    def test_consume_within_capacity_returns_zero(self) -> None:
        bucket = TokenBucket(max_tokens=10, refill_interval=60.0)
        wait = bucket.consume(5)
        assert wait == 0.0

    def test_consume_exact_capacity_returns_zero(self) -> None:
        bucket = TokenBucket(max_tokens=10, refill_interval=60.0)
        wait = bucket.consume(10)
        assert wait == 0.0

    def test_consume_reduces_available_tokens(self) -> None:
        bucket = TokenBucket(max_tokens=10, refill_interval=60.0)
        bucket.consume(3)
        assert bucket.available_tokens == 7

    def test_consume_exceeds_capacity_returns_positive_wait(self) -> None:
        bucket = TokenBucket(max_tokens=5, refill_interval=60.0)
        bucket.consume(5)  # vaciar bucket
        wait = bucket.consume(1)
        assert wait > 0.0

    def test_consume_exceeds_returns_at_most_refill_interval(self) -> None:
        bucket = TokenBucket(max_tokens=5, refill_interval=60.0)
        bucket.consume(5)  # vaciar bucket
        wait = bucket.consume(1)
        assert wait <= 60.0

    def test_consume_single_token_decrements(self) -> None:
        bucket = TokenBucket(max_tokens=3, refill_interval=10.0)
        bucket.consume(1)
        bucket.consume(1)
        assert bucket.available_tokens == 1

    def test_available_tokens_starts_at_max(self) -> None:
        bucket = TokenBucket(max_tokens=100, refill_interval=60.0)
        assert bucket.available_tokens == 100


class TestTokenBucketRefill:
    def test_refill_after_interval(self) -> None:
        bucket = TokenBucket(max_tokens=10, refill_interval=0.05)
        bucket.consume(10)  # vaciar
        assert bucket.available_tokens == 0
        time.sleep(0.1)  # esperar recarga
        wait = bucket.consume(1)
        assert wait == 0.0

    def test_no_refill_before_interval(self) -> None:
        bucket = TokenBucket(max_tokens=5, refill_interval=60.0)
        bucket.consume(5)  # vaciar
        wait = bucket.consume(1)
        assert wait > 0.0

    def test_refill_resets_to_max_not_partial(self) -> None:
        bucket = TokenBucket(max_tokens=10, refill_interval=0.05)
        bucket.consume(7)
        time.sleep(0.1)
        # Tras recarga, debe tener max_tokens completos
        bucket.consume(10)  # consume todos — si no hay 10, falla
        assert bucket.available_tokens == 0

    def test_last_refill_updated_after_refill(self) -> None:
        bucket = TokenBucket(max_tokens=5, refill_interval=0.05)
        bucket.consume(5)
        time.sleep(0.1)
        bucket.consume(1)  # dispara recarga
        # Inmediatamente después, no debería refill de nuevo
        assert bucket.available_tokens == 4


# --------------------------------------------------------------------------- #
# TokenBucket — thread-safety
# --------------------------------------------------------------------------- #
class TestTokenBucketThreadSafety:
    def test_concurrent_consume_no_negative_tokens(self) -> None:
        max_tokens = 100
        bucket = TokenBucket(max_tokens=max_tokens, refill_interval=60.0)
        results: list[float] = []
        lock = threading.Lock()

        def worker() -> None:
            wait = bucket.consume(10)
            with lock:
                results.append(wait)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactamente 10 threads pudieron consumir (100 / 10 = 10)
        zero_waits = sum(1 for w in results if w == 0.0)
        positive_waits = sum(1 for w in results if w > 0.0)
        assert zero_waits == 10
        assert positive_waits == 10
        assert bucket.available_tokens == 0

    def test_concurrent_consume_total_tokens_consistent(self) -> None:
        bucket = TokenBucket(max_tokens=50, refill_interval=60.0)
        successful = []
        lock = threading.Lock()

        def worker() -> None:
            wait = bucket.consume(1)
            if wait == 0.0:
                with lock:
                    successful.append(1)

        threads = [threading.Thread(target=worker) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(successful) == 50
        assert bucket.available_tokens == 0


# --------------------------------------------------------------------------- #
# RateLimiter
# --------------------------------------------------------------------------- #
class TestRateLimiterConsumeWeight:
    def test_consume_weight_no_sleep_when_tokens_available(self) -> None:
        with patch("chimuelo_prime.api_client.rate_limiter.time.sleep") as sleep_mock:
            cfg = RateLimitConfig(weight_limit=100, weight_window_seconds=60.0)
            rl = RateLimiter(cfg)
            rl.consume_weight(1)
            sleep_mock.assert_not_called()

    def test_consume_weight_sleeps_when_exhausted(self) -> None:
        with patch("chimuelo_prime.api_client.rate_limiter.time.sleep") as sleep_mock:
            cfg = RateLimitConfig(
                weight_limit=1,
                weight_window_seconds=60.0,
                order_limit=50,
                order_window_seconds=10.0,
            )
            rl = RateLimiter(cfg)
            rl.consume_weight(1)  # agota el bucket
            rl.consume_weight(1)  # debe disparar sleep
            sleep_mock.assert_called_once()
            sleep_seconds = sleep_mock.call_args[0][0]
            assert sleep_seconds > 0.0

    def test_consume_weight_only_touches_weight_bucket(self) -> None:
        with patch("chimuelo_prime.api_client.rate_limiter.time.sleep"):
            cfg = RateLimitConfig(
                weight_limit=100,
                weight_window_seconds=60.0,
                order_limit=50,
                order_window_seconds=10.0,
            )
            rl = RateLimiter(cfg)
            rl.consume_weight(10)
            assert rl._order_bucket.available_tokens == 50


class TestRateLimiterConsumeOrder:
    def test_consume_order_touches_both_buckets(self) -> None:
        with patch("chimuelo_prime.api_client.rate_limiter.time.sleep"):
            cfg = RateLimitConfig(
                weight_limit=100,
                weight_window_seconds=60.0,
                order_limit=50,
                order_window_seconds=10.0,
            )
            rl = RateLimiter(cfg)
            rl.consume_order(weight=5)
            assert rl._weight_bucket.available_tokens == 95
            assert rl._order_bucket.available_tokens == 49

    def test_consume_order_sleeps_when_order_bucket_exhausted(self) -> None:
        with patch("chimuelo_prime.api_client.rate_limiter.time.sleep") as sleep_mock:
            cfg = RateLimitConfig(
                weight_limit=1000,
                weight_window_seconds=60.0,
                order_limit=1,
                order_window_seconds=10.0,
            )
            rl = RateLimiter(cfg)
            rl.consume_order(weight=1)  # agota order bucket
            rl.consume_order(weight=1)  # debe dormir por order bucket
            assert sleep_mock.call_count >= 1


class TestRateLimiterConfig:
    def test_created_with_correct_weight_config(self) -> None:
        cfg = RateLimitConfig(weight_limit=500, weight_window_seconds=30.0)
        rl = RateLimiter(cfg)
        assert rl._weight_bucket.available_tokens == 500

    def test_created_with_correct_order_config(self) -> None:
        cfg = RateLimitConfig(order_limit=25, order_window_seconds=5.0)
        rl = RateLimiter(cfg)
        assert rl._order_bucket.available_tokens == 25
