"""Tests para la jerarquía de excepciones de exchange_config.

Cubre:
    - Instanciación de cada excepción.
    - Herencia correcta (isinstance checks en toda la cadena).
    - Propagación de mensaje.
    - Que se pueden capturar por clase base.
    - Que NO son genéricamente `Exception` (se pueden distinguir de otras).
"""

import pytest

from chimuelo_prime.exchange_config.exceptions import (
    ChimueloException,
    ExchangeConfigError,
    ExchangeUnreachableError,
    FilterParsingError,
    FilterValidationError,
    InvalidSymbolError,
)


# --------------------------------------------------------------------------- #
# Instanciación básica
# --------------------------------------------------------------------------- #
class TestExceptionInstantiation:
    """Cada excepción debe poder instanciarse con y sin mensaje."""

    def test_chimuelo_exception_no_message(self) -> None:
        exc = ChimueloException()
        assert isinstance(exc, Exception)

    def test_chimuelo_exception_with_message(self) -> None:
        exc = ChimueloException("algo falló")
        assert str(exc) == "algo falló"

    def test_exchange_config_error(self) -> None:
        exc = ExchangeConfigError("error de config")
        assert str(exc) == "error de config"

    def test_exchange_unreachable_error(self) -> None:
        exc = ExchangeUnreachableError("timeout en 10s")
        assert str(exc) == "timeout en 10s"

    def test_invalid_symbol_error(self) -> None:
        exc = InvalidSymbolError("XYZUSDT no existe")
        assert str(exc) == "XYZUSDT no existe"

    def test_filter_parsing_error(self) -> None:
        exc = FilterParsingError("campo faltante: tickSize")
        assert str(exc) == "campo faltante: tickSize"

    def test_filter_validation_error(self) -> None:
        exc = FilterValidationError("price=0.005 < min_price=0.01")
        assert str(exc) == "price=0.005 < min_price=0.01"


# --------------------------------------------------------------------------- #
# Jerarquía de herencia
# --------------------------------------------------------------------------- #
class TestExceptionHierarchy:
    """Verifica que cada excepción es instancia de todos sus ancestros."""

    def test_exchange_unreachable_is_exchange_config_error(self) -> None:
        exc = ExchangeUnreachableError("timeout")
        assert isinstance(exc, ExchangeConfigError)

    def test_exchange_unreachable_is_chimuelo_exception(self) -> None:
        exc = ExchangeUnreachableError("timeout")
        assert isinstance(exc, ChimueloException)

    def test_exchange_unreachable_is_base_exception(self) -> None:
        exc = ExchangeUnreachableError("timeout")
        assert isinstance(exc, Exception)

    def test_invalid_symbol_is_exchange_config_error(self) -> None:
        exc = InvalidSymbolError("XYZUSDT")
        assert isinstance(exc, ExchangeConfigError)

    def test_invalid_symbol_is_chimuelo_exception(self) -> None:
        exc = InvalidSymbolError("XYZUSDT")
        assert isinstance(exc, ChimueloException)

    def test_filter_parsing_is_exchange_config_error(self) -> None:
        exc = FilterParsingError("campo faltante")
        assert isinstance(exc, ExchangeConfigError)

    def test_filter_parsing_is_chimuelo_exception(self) -> None:
        exc = FilterParsingError("campo faltante")
        assert isinstance(exc, ChimueloException)

    def test_filter_validation_is_exchange_config_error(self) -> None:
        exc = FilterValidationError("valor viola filtro")
        assert isinstance(exc, ExchangeConfigError)

    def test_filter_validation_is_chimuelo_exception(self) -> None:
        exc = FilterValidationError("valor viola filtro")
        assert isinstance(exc, ChimueloException)


# --------------------------------------------------------------------------- #
# Capture por clase base (polimorfismo)
# --------------------------------------------------------------------------- #
class TestExceptionCapture:
    """Las subexcepciones deben ser capturables por su clase base."""

    def test_capture_unreachable_as_exchange_config_error(self) -> None:
        with pytest.raises(ExchangeConfigError):
            raise ExchangeUnreachableError("timeout")

    def test_capture_unreachable_as_chimuelo_exception(self) -> None:
        with pytest.raises(ChimueloException):
            raise ExchangeUnreachableError("timeout")

    def test_capture_invalid_symbol_as_chimuelo_exception(self) -> None:
        with pytest.raises(ChimueloException):
            raise InvalidSymbolError("XYZUSDT")

    def test_capture_filter_parsing_as_chimuelo_exception(self) -> None:
        with pytest.raises(ChimueloException):
            raise FilterParsingError("malformed")

    def test_capture_filter_validation_as_exchange_config_error(self) -> None:
        with pytest.raises(ExchangeConfigError):
            raise FilterValidationError("price OOB")

    def test_capture_filter_validation_as_chimuelo_exception(self) -> None:
        with pytest.raises(ChimueloException):
            raise FilterValidationError("price OOB")


# --------------------------------------------------------------------------- #
# Aislamiento: excepciones NO son intercambiables entre ramas
# --------------------------------------------------------------------------- #
class TestExceptionIsolation:
    """Excepciones de distintas ramas NO deben atraparse como otras ramas."""

    def test_unreachable_is_not_filter_validation(self) -> None:
        """ExchangeUnreachableError no es FilterValidationError."""
        exc = ExchangeUnreachableError("timeout")
        assert not isinstance(exc, FilterValidationError)

    def test_filter_validation_is_not_unreachable(self) -> None:
        exc = FilterValidationError("price OOB")
        assert not isinstance(exc, ExchangeUnreachableError)

    def test_invalid_symbol_is_not_filter_parsing(self) -> None:
        exc = InvalidSymbolError("XYZUSDT")
        assert not isinstance(exc, FilterParsingError)
