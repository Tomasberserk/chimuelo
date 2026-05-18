# ROADMAP — Chimuelo Prime v0.1.0

**Proyecto:** Grid Trading Bot para Binance (Testnet → Mainnet)
**Horizonte:** 7-9 semanas (7 módulos, desarrollo iterativo)
**Equipo:** Tom (PM), Marta (Arquitecta), Edison (Programador)
**Metodología:** Iterativa, bloqueante = parada total, cero deuda técnica.

---

## 📈 Visión General

```
M1: Exchange Filters (FUNDACIONAL)
    ↓
M2: API Client + Rate Limiter
    ↓
M3: Grid State Manager (SQLite)
    ↓
M4: Order Execution
    ↓
M5: Grid Engine (CORE LOGIC)
    ↓
M6: Backtesting
    ↓
M7: Bot Orchestrator + CLI
```

**Regla:** M(n) no inicia hasta que M(n-1) está 100% completo con Definition of Done cumplido.

---

## MODULE 1: Exchange Configuration & Filter Validation Service

**Alias:** "Fundacional"
**Descripción:** Single Source of Truth para los filtros operativos de Binance. Cualquier módulo que valide precio/cantidad/notional consulta aquí.

### Timeline
- **Especificación:** 18 mayo (Marta) — ✅ Completado
- **Tarea #1 (Modelos):** 18 mayo (Edison) — ✅ Completado
- **Tarea #2 (Tests):** 18-19 mayo (Edison) — 🔄 En progreso
- **Tarea #3 (Cliente HTTP):** 19-20 mayo (Edison) — ⏸️ Blocked en T#2
- **Tarea #4 (README + Merge):** 20 mayo (Edison) — ⏸️ Blocked en T#3

### Deliverables

| Entregable | Owner | Status | Blocker |
|-----------|-------|--------|---------|
| Especificación (11 secciones) | Marta | ✅ Done | — |
| `exceptions.py` (jerarquía tipificada) | Edison | ✅ Done | — |
| `models.py` (SymbolFilters, SymbolConfig) | Edison | ✅ Done | — |
| `requirements.txt` (pinned versions) | Edison | ✅ Done | — |
| Smoke-test (10 escenarios) | Edison | ✅ Done | — |
| Test suite completa (`pytest`) | Edison | 🔄 In Progress | — |
| `client.py` (HTTP wrapper) | Edison | ⏸️ Blocked | T#2 |
| `service.py` (ExchangeConfigService fachada) | Edison | ⏸️ Blocked | T#2 |
| `config_loader.py` (YAML parsing) | Edison | ⏸️ Blocked | T#2 |
| README + demo script | Edison | ⏸️ Blocked | T#3 |
| PR a develop + merge | Edison/Marta | ⏸️ Blocked | T#4 |

### Definition of Done

- [ ] `pytest --cov ≥ 90%`
- [ ] `mypy --strict` sin errores
- [ ] `ruff check && ruff format` pasando
- [ ] 10+ test cases cubriendo happy path + error cases
- [ ] Fixture JSON de `/api/v3/exchangeInfo` (real de Binance)
- [ ] README con ejemplo funcional
- [ ] PR a develop con output de tests adjunto
- [ ] Aprobación formal de Marta (auditoría línea por línea)

### Responsables

- **Marta:** auditoría de cada entregable, decisión final.
- **Edison:** implementación, testing, documentación.

---

## MODULE 2: API Client & Rate Limiter

**Alias:** "Intermediario de Binance"
**Descripción:** Cliente HTTP autenticado para Binance con gestión de rate limits. Token bucket pattern. Manejo tipificado de excepciones. Base para todos los módulos que hacen API calls.

### Dependencias
- **Requiere:** M1 completado al 100%.
- **Usa:** `SymbolFilters` + `ExchangeConfigService` de M1.

### Timeline (Estimado)

- **Especificación:** 20-21 mayo (Marta) — ⏸️ After M1
- **Implementación:** 21-23 mayo (Edison)
- **Auditoría:** 23 mayo (Marta)
- **Target:** 23 mayo completado

### Entregables Esperados

| Archivo | Descripción |
|---------|-------------|
| `api_client.py` | Cliente HTTP con sesiones, timeouts, retry logic |
| `rate_limiter.py` | Token bucket: 1200 weight/min, 50 orders/10s |
| `decorators.py` | Decorador `@rate_limit()` para métodos |
| `exceptions.py` (extensión) | `APIError`, `RateLimitExceeded`, `AuthError` |
| `models.py` (extensión) | `APIRequest`, `APIResponse` wrappers |
| Tests | Mock de respuestas Binance, escenarios de throttling |

### Key Features

1. **Rate Limiting Token Bucket**
   - Peso de request (weight) configurable por endpoint.
   - Fallback a espera (sleep) si se alcanza límite.
   - Logging estructurado de eventos de throttling.

2. **Retry Logic**
   - Exponential backoff en 429 (Too Many Requests).
   - Máximo 3 reintentos antes de fallar.
   - Jitter para evitar thundering herd.

3. **Autenticación**
   - API Key + Secret de archivo YAML (nunca hardcoded).
   - Firma HMAC-SHA256 automática en requests autenticados.
   - Timestamp sincronizado con Binance.

4. **Tipado Completo**
   - `mypy --strict` sin `Any`.
   - Respuestas parseadas con Pydantic.

### Testing Strategy

```python
# Test 1: Rate limiter respeta 1200 weight/min
# Test 2: Rate limiter espera antes de exceder límite
# Test 3: Retry con backoff exponencial en 429
# Test 4: Firma HMAC correcta en requests autenticados
# Test 5: Timeout en 10s
# Test 6: Pool de sesiones (max 10 conexiones concurrentes)
```

---

## MODULE 3: Grid State Manager

**Alias:** "Persistencia & Reconciliación"
**Descripción:** Gestiona el estado persistente del grid en SQLite. Mantiene sincronización con órdenes reales en Binance. Recoverable ante caídas.

### Dependencias
- **Requiere:** M1 + M2 completados.
- **Usa:** `ExchangeConfigService` (M1) + `APIClient` (M2).

### Timeline (Estimado)

- **Especificación:** 23-24 mayo (Marta)
- **Implementación:** 24-26 mayo (Edison)
- **Auditoría:** 26 mayo (Marta)
- **Target:** 26 mayo completado

### Entregables

| Archivo | Descripción |
|---------|-------------|
| `schema.py` | Modelos SQLAlchemy para órdenes, niveles, snapshots |
| `database.py` | Inicialización, migrations, transacciones |
| `grid_state.py` | GridState: lectura/escritura persistente |
| `reconciler.py` | Reconciliación con `/api/v3/openOrders` |
| Tests | Test de transacciones, corrupciones simuladas, recovery |

### Key Features

1. **Persistencia Transaccional**
   - Tabla `orders`: order_id, symbol, side, price, qty, status, timestamp.
   - Tabla `grid_levels`: level_id, lower, upper, buy_order_id, sell_order_id.
   - Tabla `snapshots`: equity, inventory, cash, timestamp (para análisis).

2. **Reconciliación al Iniciar**
   - Fetch `/api/v3/openOrders`.
   - Diff contra DB local.
   - Resolución de inconsistencias (órdenes que se ejecutaron, canceladas, etc.).
   - Logging de divergencias.

3. **Atomicidad**
   - Transacciones ACID: si falla la mitad, todo se revierte.
   - Locks para evitar race conditions (aunque M1-M5 son sync).

### Testing

```python
# Test 1: Crear grid, persistir, recuperar intacto
# Test 2: Simular caída a mitad de ejecución, reconciliar
# Test 3: Detectar orden que se ejecutó sin que el bot lo sepa
# Test 4: Detectar orden cancelada por timeout o usuario
# Test 5: Transacción fallida se revierte completamente
```

---

## MODULE 4: Order Execution & Lifecycle

**Alias:** "Colocación y Seguimiento"
**Descripción:** Interfaz para crear, cancelar, modificar órdenes en Binance. Seguimiento de ciclo de vida. Manejo de rechazos (filtros Binance, saldo insuficiente, etc.).

### Dependencias
- **Requiere:** M1 + M2 + M3 completados.
- **Usa:** `SymbolFilters` (M1) + `APIClient` (M2) + `GridState` (M3).

### Timeline (Estimado)

- **Especificación:** 26-27 mayo (Marta)
- **Implementación:** 27-29 mayo (Edison)
- **Auditoría:** 29 mayo (Marta)
- **Target:** 29 mayo completado

### Entregables

| Archivo | Descripción |
|---------|-------------|
| `order_manager.py` | Create, cancel, modify, query órdenes |
| `lifecycle.py` | Estados: NEW, PARTIALLY_FILLED, FILLED, CANCELED |
| `validation.py` | Pre-validar orden antes de enviar (filtros M1) |
| `exceptions.py` (extensión) | `OrderRejectedError`, `InsufficientBalanceError` |
| Tests | Mock orders, estados transicionales, rechazos |

### Key Features

1. **Validación Pre-Orden**
   - Usa `SymbolFilters.validate_price/qty/notional()` de M1.
   - Si falla, rechaza localmente sin tocar Binance.
   - Logging del motivo del rechazo.

2. **Ciclo de Vida**
   ```
   NEW → PARTIALLY_FILLED (opcional) → FILLED
   NEW → CANCELED (por usuario/timeout/gap)
   ```

3. **Tracking**
   - Pool de órdenes activas monitoreado.
   - WebSocket (si se usa en futuro) o polling en `status()`.
   - Callbacks al completar ciclos.

### Testing

```python
# Test 1: Crear orden válida, se ejecuta
# Test 2: Crear orden inválida (price < min_price), rechaza pre-validación
# Test 3: Orden parcialmente ejecutada, continúa esperando
# Test 4: Cancelar orden activa
# Test 5: Timeout en orden (>5min sin ejecución), cancela
```

---

## MODULE 5: Grid Engine (CORE LOGIC)

**Alias:** "Corazón del Bot"
**Descripción:** Lógica central del grid trading. Calcula niveles, distribuye capital, coloca órdenes, procesa ciclos completos (compra→venta). Multi-activo con inyección de dependencias.

### Dependencias
- **Requiere:** M1 + M2 + M3 + M4 completados.
- **Usa:** Todos los módulos anteriores.

### Timeline (Estimado)

- **Especificación:** 29-30 mayo (Marta)
- **Implementación:** 30 mayo - 2 junio (Edison)
- **Auditoría:** 2 junio (Marta)
- **Target:** 2 junio completado

### Entregables

| Archivo | Descripción |
|---------|-------------|
| `grid_engine.py` | Lógica principal: niveles, distribución, ciclos |
| `level_calculator.py` | Cálculo de grid levels (aritmético v1, geométrico v2) |
| `cycle_manager.py` | Seguimiento de ciclos (compra → venta → ganancia) |
| `risk_manager.py` | Soft stop, hard stop, ruptura de régimen |
| Tests | Backtesting lógica, ciclos, edge cases |

### Key Features

1. **Cálculo de Niveles**
   - **V1 (Aritmético):** spacing uniforme.
   - **V2 (Geométrico):** spacing logarítmico (roadmap).
   - Usa `SymbolConfig.upper_bound`, `lower_bound`, `grid_levels`.

2. **Distribución de Capital**
   - Uniforme v1 (cada nivel = capital_total / grid_levels).
   - Ponderado v2 (por volatilidad histórica, risk parity).

3. **Ciclos de Grid**
   - Coloca buy en cada nivel (via M4: OrderManager).
   - Cuando precio toca nivel, coloca sell correspondiente.
   - Registra ganancia del ciclo.

4. **Gestión de Riesgo**
   - **Soft stop:** precio rompe lower_bound → pausar compras.
   - **Hard stop:** drawdown > 8% → liquidar todo.
   - **Ruptura de régimen:** ATR 2x → pausar bot.

### Testing (Backtesting)

```python
# Test 1: Grid se coloca correctamente en rango
# Test 2: Ciclos se completan buy→sell sin error
# Test 3: Soft stop previene over-leveraging
# Test 4: Hard stop ejecuta liquidación
# Test 5: Ruptura de régimen pausa correctamente
# Test 6: Multi-activo con risk parity (DOGE + SOL)
```

---

## MODULE 6: Backtesting Engine

**Alias:** "Validación Offline"
**Descripción:** Integración con `vectorbt` para backtesting de la estrategia sobre datos históricos. Calcula Sortino, Calmar, Profit Factor, etc. Umbral de éxito debe cumplirse antes de pasar a testnet.

### Dependencias
- **Requiere:** M1 + M5 completados (no necesita M2-M4 para backtest offline).

### Timeline (Estimado)

- **Especificación:** 2-3 junio (Marta)
- **Implementación:** 3-5 junio (Edison)
- **Auditoría:** 5 junio (Marta)
- **Target:** 5 junio completado

### Entregables

| Archivo | Descripción |
|---------|-------------|
| `backtest_engine.py` | Wrapper de vectorbt con configuración por símbolo |
| `performance_metrics.py` | Sortino, Calmar, Profit Factor, drawdown |
| `historical_data.py` | Fetch 6 meses de velas 1h via Binance API |
| `report_generator.py` | Reporte HTML/JSON con gráficos |
| Tests | Mock de datos históricos, métricas consistentes |

### Umbrales de Éxito (Debe cumplir)

```
Sortino Ratio > 1.5
Calmar Ratio > 1.0
Profit Factor > 1.5
Max Drawdown < 10%
Win Rate > 55%
```

Si NO cumple: **revisar parámetros del grid, iterar**, no pasar a testnet.

### Testing

```python
# Test 1: Sortino calculado correctamente
# Test 2: Calmar refleja retorno/drawdown
# Test 3: Profit Factor >= 1.0 en data rentable
# Test 4: Reporte HTML se genera sin error
# Test 5: Multi-activo, métricas agregadas correctamente
```

---

## MODULE 7: Bot Orchestrator & CLI

**Alias:** "Interfaz Pública"
**Descripción:** Orquestador que coordina los 6 módulos anteriores. CLI para start/stop/status. Multi-activo con balanceo de capital (risk parity). Logging centralizado.

### Dependencias
- **Requiere:** Todos los módulos (M1-M6) completados.

### Timeline (Estimado)

- **Especificación:** 5-6 junio (Marta)
- **Implementación:** 6-8 junio (Edison)
- **Auditoría:** 8 junio (Marta)
- **Target:** 8 junio completado

### Entregables

| Archivo | Descripción |
|---------|-------------|
| `orchestrator.py` | Coordina M1-M6, maneja ciclo de vida del bot |
| `cli.py` | CLI con Click: start, stop, status, backtest |
| `config_manager.py` | Carga y valida `chimuelo.yaml` (multi-activo) |
| `monitoring.py` | Logging centralizado, alertas, webhooks |
| Tests | Full integration test, simulación de fallo/recovery |

### Features

1. **CLI Completo**
   ```bash
   $ chimuelo start --config chimuelo.yaml --mode testnet
   $ chimuelo stop
   $ chimuelo status
   $ chimuelo backtest --symbol SOLUSDT --days 180
   ```

2. **Multi-Activo**
   - Carga múltiples `SymbolConfig` desde YAML.
   - Distribuye capital con risk parity.
   - Instancias paralelas del GridEngine (una por activo).

3. **Recuperación de Fallos**
   - Si el bot se cae, reinicia desde checkpoint SQLite.
   - Reconcilia estado con Binance.
   - Continúa operando sin intervención.

4. **Alertas**
   - Slack/Email en eventos críticos (hard stop, ruptura de régimen).
   - Reporte diario de PnL.

### Testing

```python
# Test 1: Start bot, opera sin error por 5min simulados
# Test 2: Stop bot, sale limpio, persiste estado
# Test 3: Caída simulada, reinicio recupera correctamente
# Test 4: Multi-activo, capital distribuido por risk parity
# Test 5: CLI comanda se procesa correctamente
```

---

## 📊 Gantt Chart (Estimado)

```
Semana 1 (18-24 mayo)
├─ M1: ████████████ 100%
├─ M2: ░░░░░░░░░░░░ 0% (blocked)
└─ M3-M7: ░░░░░░░░░░░░ 0% (blocked)

Semana 2 (24-31 mayo)
├─ M1: ████████████ 100% (DONE)
├─ M2: ████░░░░░░░░ 50% (in progress)
├─ M3: ░░░░░░░░░░░░ 0% (blocked)
└─ M4-M7: ░░░░░░░░░░░░ 0% (blocked)

Semana 3 (1-7 junio)
├─ M1-M2: ████████████ 100% (DONE)
├─ M3: ████░░░░░░░░ 50% (in progress)
├─ M4-M5: ░░░░░░░░░░░░ 0% (blocked)
└─ M6-M7: ░░░░░░░░░░░░ 0% (blocked)

Semana 4 (8-14 junio)
├─ M1-M3: ████████████ 100% (DONE)
├─ M4: ████░░░░░░░░ 50% (in progress)
├─ M5: ░░░░░░░░░░░░ 0% (blocked)
└─ M6-M7: ░░░░░░░░░░░░ 0% (blocked)

Semana 5 (15-21 junio)
├─ M1-M4: ████████████ 100% (DONE)
├─ M5: ████░░░░░░░░ 50% (in progress)
├─ M6: ░░░░░░░░░░░░ 0% (blocked)
└─ M7: ░░░░░░░░░░░░ 0% (blocked)

Semana 6 (22-28 junio)
├─ M1-M5: ████████████ 100% (DONE)
├─ M6: ████░░░░░░░░ 50% (in progress)
└─ M7: ░░░░░░░░░░░░ 0% (blocked)

Semana 7 (29-5 julio)
├─ M1-M6: ████████████ 100% (DONE)
└─ M7: ████░░░░░░░░ 50% (in progress)

Semana 8+ (5+ julio)
├─ M1-M7: ████████████ 100% (DONE)
├─ Testnet: fase de testing real
└─ Mainnet: (future)
```

---

## 🎯 Criterios de Éxito

### Por Módulo
- Definition of Done 100% cumplida.
- Tests ≥ 90% coverage.
- `mypy --strict` + `ruff` pasando.
- Aprobación formal de Marta (auditoría).

### Por Hito (M1 → M7)
- Cada módulo completado antes de iniciar siguiente.
- Cero deuda técnica.
- Documentación actualizada.

### Final (v0.1.0)
- Backtesting: Sortino > 1.5, Calmar > 1.0 (M6).
- Bot operando en testnet sin intervención > 72h (M7).
- Multi-activo (SOL + DOGE) balanceado por risk parity.
- Recuperable de fallos de red/proceso.

---

## 🚨 Riesgos y Mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|--------|-----------|
| API Binance cambia filtros | Media | Alto | Validación en tiempo real, alerts |
| Bug en validación decimal | Baja | Crítico | Tests exhaustivos, auditoría de Marta |
| Deuda técnica acumulada | Alta | Alto | Bloqueo estricto de M(n-1), Definition of Done |
| Timeline slip (Edison se atrasa) | Media | Medio | Buffer de 2 semanas, scope claramente definido |
| Slippage > estimado en testnet | Media | Medio | Buffer de capital 20%, logs detallados |

---

## 📞 Escalación

| Situación | Acción |
|-----------|--------|
| Ambigüedad en spec | Pedir clarificación a Marta antes de codear |
| Edison bloquea | Marta revisa, toma decisión, comunica |
| Falla en auditoría | Edison itera hasta cumplir Definition of Done |
| Risk/timeline crítical | Tom decide prioridades, Marta asesora |

---

## 📚 Referencias

- **MARTA.md:** roles y reglas de Marta.
- **EDISON.md:** stack, checklist, flujo de Edison.
- **PROJECT_STATUS.md:** estado actual detallado.
- **M1 SPEC:** especificación del Módulo 1 (plantilla para M2-M7).

---

**Última actualización:** 18 de mayo de 2026
**Versión:** 1.0
**Estado:** Activo (desarrollo en progreso)
