"""Excepciones tipificadas del módulo exchange_config.

Jerarquía:
    ChimueloException (raíz del proyecto)
    └── ExchangeConfigError
        ├── ExchangeUnreachableError    # timeout, 5xx, network
        ├── InvalidSymbolError          # símbolo no existe en exchangeInfo
        ├── FilterParsingError          # estructura inesperada en respuesta
        └── FilterValidationError       # valor viola un filtro

Regla del proyecto: ningún módulo debe hacer `except Exception` genérico.
Captura siempre la excepción tipificada correspondiente.
"""


class ChimueloException(Exception):
    """Raíz de todas las excepciones del proyecto Chimuelo Prime."""


class ExchangeConfigError(ChimueloException):
    """Raíz de errores del módulo exchange_config."""


class ExchangeUnreachableError(ExchangeConfigError):
    """La API de Binance no respondió (timeout, error 5xx, fallo de red)."""


class InvalidSymbolError(ExchangeConfigError):
    """El símbolo solicitado no existe en `/api/v3/exchangeInfo`."""


class FilterParsingError(ExchangeConfigError):
    """La respuesta del exchange tiene estructura inesperada o filtros faltantes."""


class FilterValidationError(ExchangeConfigError):
    """Un valor (precio, cantidad o notional) viola un filtro del símbolo."""


# --------------------------------------------------------------------------- #
# ConfigError — carga y validación de configuración YAML
# --------------------------------------------------------------------------- #
class ConfigError(ChimueloException):
    """Raíz de errores de carga y validación de configuración del proyecto."""


class ConfigFileNotFoundError(ConfigError):
    """El archivo YAML de configuración no fue encontrado en la ruta indicada."""


class ConfigValidationError(ConfigError):
    """El contenido del YAML no cumple el schema esperado (campos faltantes, tipos inválidos)."""
