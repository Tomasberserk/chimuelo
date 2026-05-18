"""Inicialización y configuración del engine SQLite para M3.

Responsabilidades:
    - build_engine(): crea Engine, habilita WAL + FK constraints, crea tablas.

WAL mode (Write-Ahead Logging):
    - Permite lecturas concurrentes mientras hay escrituras en curso.
    - No disponible en :memory: (SQLite en memoria usa journal por defecto).
    - Crítico para M7 donde múltiples GridEngines pueden leer simultáneamente.

FK constraints:
    SQLite no enforcea FKs por defecto. Se activan con PRAGMA foreign_keys=ON
    en cada conexión nueva. Garantiza integridad referencial entre GridLevel y Order.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event

from chimuelo_prime.grid_state.schema import Base


def build_engine(db_url: str = "sqlite:///chimuelo.db") -> Engine:
    """Crea e inicializa el engine SQLite.

    Crea todas las tablas si no existen (idempotente).
    Configura PRAGMA foreign_keys=ON y, si es file-based, journal_mode=WAL.

    Args:
        db_url: URL de SQLAlchemy. Ejemplos:
            - "sqlite:///chimuelo.db"   (archivo relativo)
            - "sqlite:////abs/path.db"  (ruta absoluta)
            - "sqlite:///:memory:"      (en memoria, para tests)

    Returns:
        Engine listo para usar con Session().
    """
    engine = create_engine(db_url, echo=False)
    _register_sqlite_pragmas(engine, db_url=db_url)
    Base.metadata.create_all(engine)
    return engine


def _register_sqlite_pragmas(engine: Engine, db_url: str) -> None:
    """Registra el listener que activa pragmas SQLite en cada nueva conexión."""
    is_memory = ":memory:" in db_url

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: Any, _connection_record: Any) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        if not is_memory:
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
