# PROJECT_STATUS.md — Estado de Chimuelo Prime

**Última actualización:** 18 de mayo de 2026 02:30 UTC
**Versión del proyecto:** 0.1.0-dev (Módulo 1 en desarrollo)

---

## 📊 Resumen Ejecutivo

**Chimuelo Prime** es un bot de grid trading automatizado para Binance Testnet/Mainnet, enfocado en estrategia diversificada (activos de volatilidad estructural + caótica) con gestión rigurosa de riesgo y arquitectura escalable.

### Estado General

| Área | Estado | Completitud |
|------|--------|-------------|
| **Diseño Matemático** | ✅ Completo | 100% |
| **Arquitectura de Software** | ✅ Especificada | 100% |
| **Módulo 1** | 🔄 En desarrollo | 20% |
| **Módulos 2-7** | ⏸️ Blocked (esperando M1) | 0% |
| **Documentación** | ✅ En progreso | 60% |
| **Testing Infrastructure** | ✅ Definido | 100% |

---

## 🎯 Milestones Completados

### Fase 0: Parametrización Matemática

**Fechas:** 17-18 mayo 2026
**Entregables:**
- ✅ Cálculo de parámetros críticos para SOL/USDT (ATR, límites, spacing, capital).
- ✅ Auditoría de supuestos: conversión de ATR 4h → ATR 1d, validación de MIN_NOTIONAL real via API.
- ✅ Definición de métricas de éxito (Sortino > 1.5, Calmar > 1.0, Profit Factor > 1.5).
- ✅ Circuit breaker con drawdown del portfolio (-8%) y pausa soft en ruptura de rango.
- ✅ Backlog de risk parity multi-activo (DOGE/USDT como segundo activo).

**Decisiones Arquitectónicas:**
- Grid de 40 niveles, spacing aritmético v1 → geométrico v2.
- Decimal-only, cero floats (regla dura).
- Persistencia SQLite para estado transaccional del grid.
- Reconciliación de estado al iniciar vs `/api/v3/openOrders`.

**Documentación:**
- Tabla de parámetros validados (90 días de velas 1D).
- Justificación teórica de cada decisión (Sharpe → Sortino, ATR diario vs 4h, etc.).

---

### Fase 1a: Especificación Técnica — Módulo 1

**Fechas:** 18 mayo 2026
**Entregables:**
- ✅ Especificación completa de `Exchange Configuration & Filter Validation Service`.
- ✅ Definición de responsabilidades (qué entra, qué no entra en M1).
- ✅ Modelo de dominio: `SymbolFilters` (inmutable, Decimal-only) + `SymbolConfig` (para inyección de dependencias).
- ✅ Excepciones tipificadas (jerarquía, casos de uso).
- ✅ Testing strategy: `pytest + responses`, cobertura ≥ 90%.
- ✅ Definition of Done (7 criterios, incluyendo `mypy --strict` y `ruff`).
- ✅ Principios arquitectónicos: SRP, Open/Closed, Single Source of Truth.

**Documentación:**
- 11 secciones de especificación (propósito, responsabilidades, estructura, modelos, excepciones, logging, config, testing, control de versiones, Definition of Done, qué NO aceptar).

---

### Fase 1b: Implementación Inicial — Módulo 1

**Fechas:** 18 mayo 2026 02:00-02:30 UTC
**Entregables:**
- ✅ Estructura de carpetas exacta (`chimuelo_prime/exchange_config/`, `tests/`, `config/`).
- ✅ `requirements.txt` con versiones fijadas (pydantic 2.9.2, structlog, pytest, responses, mypy, ruff).
- ✅ `exceptions.py`: jerarquía tipificada (ChimueloException → ExchangeConfigError → subcategorías).
- ✅ `models.py`: 
  - `SymbolFilters` (frozen, strict, Decimal-only).
  - Métodos: `validate_price()`, `validate_quantity()`, `validate_notional()`, `round_price_to_tick()`, `round_qty_to_step()`.
  - `SymbolConfig` para inyección de dependencias.
  - Field validators que rechazan floats explícitamente.
  - Validación cruzada en `model_post_init()`.
- ✅ Smoke-test manual (10 escenarios, todos pasando).

**Decisiones Técnicas Documentadas:**
1. Pydantic v2 con `frozen=True` para inmutabilidad real.
2. `ROUND_DOWN` explícito en redondeos (decisión crítica para órdenes de compra/venta).
3. Validación de múltiplos vía aritmética Decimal exacta.
4. Field validators en modo `before` para bloquear floats disfrazados.

**Auditoría de Marta:**
- ✅ Código aprobado técnicamente.
- ⚠️ Desviación menor: Edison creó `exceptions.py` sin permiso explícito (justificación válida, pero marca precedente).
- ✅ Humo-test cubre 10 escenarios críticos.

---

## 🔄 Trabajo en Progreso — Módulo 1

### Tarea #2: Suite de Tests Completa

**Estado:** Pendiente de auditoría de Marta → Edison ejecuta.

**Entregables esperados:**
- Test unitarios para cada método de `SymbolFilters`.
- Test de excepciones tipificadas (casos de error).
- Test de `SymbolConfig` con validación cruzada.
- Mock de `/api/v3/exchangeInfo` con fixture JSON real de Binance.
- Output final: `pytest --cov ≥ 90%`, `mypy --strict OK`, `ruff OK`.

**Timeline estimado:** 4-6 horas (Edison).

---

### Tarea #3: Cliente HTTP Base (ExchangeConfigService)

**Estado:** No iniciado (esperando T#2).

**Descripción:**
- `client.py`: wrapper HTTP para endpoints públicos de Binance.
- `service.py`: `ExchangeConfigService` — fachada pública que carga `/api/v3/exchangeInfo`, parsea, construye `SymbolFilters`.
- `config_loader.py`: carga y valida `chimuelo.yaml`.
- Error handling tipificado.

**Dependencias:** Tarea #2 debe estar completada.

---

### Tarea #4: README + Entrega Final M1

**Estado:** No iniciado (esperando T#3).

**Entregables:**
- README.md del módulo con ejemplo de uso.
- Demo script: cargar config → validar filtros SOLUSDT → output estructurado.
- PR final a `develop` con aprobación de Marta.

---

## ⏸️ Bloqueantes Actuales

**NINGUNO.** El proyecto está en flow. Edison tiene luz verde para ejecutar Tarea #2 tan pronto Marta dé el OK (esperado en esta sesión).

---

## 📋 Módulos Pendientes (Roadmap)

| Módulo | Nombre | Descripción | Estado | Timeline |
|--------|--------|-------------|--------|----------|
| **M2** | API Client & Rate Limiter | Cliente HTTP autenticado + token bucket | ⏸️ Blocked | Semana 2 |
| **M3** | Grid State Manager | Persistencia SQLite + reconciliación de órdenes | ⏸️ Blocked | Semana 2-3 |
| **M4** | Order Execution & Lifecycle | Colocación, cancelación, seguimiento de órdenes | ⏸️ Blocked | Semana 3 |
| **M5** | Grid Engine (Core Logic) | Cálculo de niveles, distribución de capital, cierre de ciclos | ⏸️ Blocked | Semana 4-5 |
| **M6** | Backtesting Engine | vectorbt integration, métricas de performance | ⏸️ Blocked | Semana 5-6 |
| **M7** | Bot Orchestrator & CLI | Orquestación multi-activo, CLI para start/stop/status | ⏸️ Blocked | Semana 6-7 |

---

## 📚 Documentación Actual

| Documento | Estado | Ubicación |
|-----------|--------|-----------|
| **MARTA.md** | ✅ Completo | `docs/MARTA.md` |
| **EDISON.md** | ✅ Completo | `docs/EDISON.md` |
| **PROJECT_STATUS.md** | ✅ En progreso | `docs/PROJECT_STATUS.md` (este archivo) |
| **ROADMAP.md** | 🔄 En creación | `docs/ROADMAP.md` |
| **SPEC_M1.md** | ✅ Completo | `docs/specs/M1_SPEC.md` |
| **SPEC_M2.md** | ⏸️ Por hacer | `docs/specs/M2_SPEC.md` |
| Code comments | ✅ En progreso | Inline (docstrings, justificaciones) |

---

## 🎓 Decisiones Clave Hasta Aquí

### 1. **Spread de Spacing: Aritmético v1 → Geométrico v2**
- **Decisión:** mantener aritmético para v1 (simplifica cálculo inicial).
- **Razón:** SOL/USDT con rango 24.8% no es tan extremo como para que la degradación sea crítica.
- **Backlog:** migrar a geométrico en v2, especialmente con DOGE/PEPE (volatilidad caótica, colas gordas).

### 2. **Decimal-Only Desde Día 1**
- **Decisión:** bloqueo defensivo de floats a nivel de modelos.
- **Razón:** Binance rechaza órdenes con floats (código -1013). Mejor fallar en validación que en producción.

### 3. **Modelos Inmutables (frozen=True)**
- **Decisión:** `SymbolFilters` y `SymbolConfig` frozen.
- **Razón:** Thread-safety, previene bugs de aliasing, fuerza creación de instancias nuevas si los filtros cambian.

### 4. **Inyección de Dependencias desde Módulo 1**
- **Decisión:** `SymbolConfig` abstracto para que M5 (GridEngine) no conozca símbolos específicos.
- **Razón:** Open/Closed Principle (SOLID-O). Futuro multi-activo sin refactor de motor.

### 5. **Testing Obligatorio ≥ 90%**
- **Decisión:** límite duro de cobertura, no sugerencia.
- **Razón:** Grid trading es finanzas. Bugs no-detectados = pérdida de dinero.

### 6. **Persistencia SQLite Transaccional**
- **Decisión:** SQLite (no JSON file-based) para estado del grid.
- **Razón:** transaccionalidad ACID. Si el bot falla a mitad de operación, recupera sin inconsistencias.

### 7. **Backtesting Antes de Testnet**
- **Decisión:** `vectorbt` para backtesting offline.
- **Razón:** validar rentabilidad de la lógica antes de tocar dinero (simulado o real).

---

## 🚀 Hitos Próximos (1-2 Semanas)

### Semana 1
- [ ] **Tarea #2 (Edison):** Suite de tests M1 completa, cobertura ≥ 90%.
- [ ] **Tarea #3 (Edison):** Cliente HTTP + `ExchangeConfigService` + `config_loader`.
- [ ] **Tarea #4 (Edison):** README + demo + merge a develop.
- [ ] **Marta audita:** cada entregable línea por línea.

### Semana 2
- [ ] **ROADMAP.md:** elaboración detallada de M2-M7 con estimaciones.
- [ ] **M2 Spec (Marta):** especificación de API Client autenticado + rate limiter.
- [ ] **M2 Inicio (Edison):** arquitectura de M2, tests base.

### Semana 3
- [ ] M2 completado.
- [ ] M3 iniciado (Grid State Manager).

---

## 📊 Métricas de Éxito (Definidas)

### Backtesting (antes de testnet)
- **Sortino Ratio > 1.5** — penaliza desviación a la baja.
- **Calmar Ratio > 1.0** — retorno anual ≥ max drawdown.
- **Profit Factor > 1.5** — ganancia total / pérdida total.
- **Max Drawdown < 10%** — límite de pérdida.
- **Win Rate > 55%** — proporción de ciclos rentables.

### Testing
- **Cobertura ≥ 90%** — líneas ejecutadas en tests.
- **mypy --strict** — tipado completo, sin `Any` implícito.
- **ruff check + format** — linting + formatting automático.

### Producción (testnet)
- **Uptime > 99%** — disponibilidad del bot.
- **Drawdown real < 8%** — hard stop activado antes de degradarse.
- **Order fill rate > 95%** — órdenes ejecutadas (no rechazadas por filtros).

---

## 🔐 Supuestos y Riesgos

### Supuestos
1. **Volatilidad estructural:** SOL/USDT mantiene patrón reversible (no rupturas de tendencia).
2. **Liquidez Binance:** spread pequeño, no hay slippage importante en órdenes de 6 USDT.
3. **API Binance estable:** uptime > 99.9%, rate limits conocidos.
4. **Testnet refleja producción:** mismo motor, mismos filtros.

### Riesgos

| Riesgo | Impacto | Mitigación |
|--------|---------|-----------|
| Ruptura de régimen (ATR 2x) | Bot gira en pérdida | Soft stop + pausa automática |
| Caída flash (crash 15%+) | Liquidación forzada | Hard stop en -8% drawdown |
| API Binance down | Bot no puede operar | Alertas, fallback a manual |
| Bug en validación de órdenes | Órdenes rechazadas, asincronía | Testing 90%, type hints estrictos |
| Slippage > estimado | Margin menor por ciclo | Capital buffer 20% + validación notional |

---

## 💬 Próxima Sesión: Qué Esperar

1. **Edison ejecuta Tarea #2** (tests completos para M1).
2. **Marta audita** línea por línea, aprueba o rechaza.
3. Si aprobado → Edison Tarea #3 (cliente HTTP).
4. Si rechazado → Edison itera hasta cumplir Definition of Done.
5. **Tom propone** nuevas estrategias (DOGE/USDT, ajustes de parámetros).
6. **Marta audita** con critical flaw analysis.
7. **Ciclo continúa** hasta completar M1 100%.

---

## 📝 Notas Operativas

- **Timezone:** América (Colombia, UTC-5). Sesiones típicamente en horarios PM.
- **Responsables:** Tom (PM), Marta (Arquitecta), Edison (Programador).
- **Cadencia:** iterativo, bloqueante = se detiene todo, cero deuda técnica.
- **Comunicación:** aclaraciones antes de decidir, documentación siempre.

---

**Versión:** 1.0
**Status:** En desarrollo activo
**Próxima revisión:** después de Tarea #2 (Edison)
