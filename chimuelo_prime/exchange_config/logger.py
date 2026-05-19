"""Configuración de observabilidad para Chimuelo Prime.

Exporta:
    - `configure_logging(level, fmt)`: debe llamarse UNA vez al inicio del proceso.
    - `get_logger(name)`: retorna un logger structlog listo para usar.

Decisión de diseño:
    - Modo "json" → `JSONRenderer`: salida parseable por Datadog, Loki, etc.
    - Modo "console" → `ConsoleRenderer`: legible en desarrollo local.
    - El nivel de logging y el formato se inyectan desde `ChimueloConfig`
      (cargada por `config_loader.py`). NUNCA hardcodeados aquí.

REGLA: ningún módulo usa `print()`. Todos usan `get_logger(__name__)`.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, cast

import structlog
import structlog.contextvars
import structlog.dev
import structlog.processors
import structlog.stdlib


def configure_logging(level: str = "info", fmt: str = "json") -> None:  # pragma: no cover
    """Configura structlog y el logging estándar de Python.

    Args:
        level: nivel mínimo de log ("debug", "info", "warning", "error", "critical").
        fmt:   formato de salida ("json" para producción, "console" para desarrollo).

    Debe llamarse exactamente UNA vez, al inicio del proceso (antes de
    instanciar cualquier módulo que haga logging).
    """
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    renderer: Any
    if fmt == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
        force=True,  # Reemplaza handlers existentes (útil en tests)
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Retorna un logger structlog pre-configurado ligado a `name`.

    Args:
        name: identificador del módulo (convención: pasar `__name__`).

    Returns:
        Logger con el contexto de módulo adjunto.

    Nota de tipos:
        `structlog.get_logger()` retorna `BoundLoggerLazyProxy` internamente,
        pero el proxy delega al `wrapper_class=BoundLogger` configurado en
        `configure_logging()`. El `type: ignore` es necesario porque los stubs
        de structlog no expresan este patrón de proxy→wrapper.
    """
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
