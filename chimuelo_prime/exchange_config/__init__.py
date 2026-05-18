"""Exports públicos del módulo exchange_config.

Sólo se exponen las clases e interfaces que forman la API pública
del módulo. Las implementaciones internas permanecen privadas.
"""

from chimuelo_prime.exchange_config.client import BinancePublicClient
from chimuelo_prime.exchange_config.exceptions import (
    ChimueloException,
    ConfigError,
    ConfigFileNotFoundError,
    ConfigValidationError,
    ExchangeConfigError,
    ExchangeUnreachableError,
    FilterParsingError,
    FilterValidationError,
    InvalidSymbolError,
)
from chimuelo_prime.exchange_config.logger import configure_logging, get_logger
from chimuelo_prime.exchange_config.models import SymbolConfig, SymbolFilters
from chimuelo_prime.exchange_config.service import ExchangeConfigService

__all__ = [
    # Excepciones
    "ChimueloException",
    "ExchangeConfigError",
    "ExchangeUnreachableError",
    "FilterParsingError",
    "FilterValidationError",
    "InvalidSymbolError",
    "ConfigError",
    "ConfigFileNotFoundError",
    "ConfigValidationError",
    # Modelos de dominio
    "SymbolFilters",
    "SymbolConfig",
    # Logging
    "configure_logging",
    "get_logger",
    # Servicios
    "BinancePublicClient",
    "ExchangeConfigService",
]
