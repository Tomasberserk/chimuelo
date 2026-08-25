# 🚀 INICIO AQUÍ — Chimuelo Prime Session Launcher

**Bienvenido a Chimuelo Prime.** Lee esto primero (2 minutos).

---

## ¿Qué es Chimuelo Prime?

**Chimuelo Prime** es un sistema integral de trading cuantitativo y algorítmico diseñado para Binance Spot (Testnet / Mainnet) con:
- **Estrategia Diversificada:** Grid Trading de Doble Régimen (volatilidad estructural y caótica) + **Estrategias Cuantitativas de Señales (M9)** optimizadas para micro-cuentas ($25 USD).
- **Gestión Rigurosa de Riesgo:** Circuit breakers intra-diarios (-4%), hard stop de portfolio (-8%), stops dinámicos basados en ATR 14 y filtro de régimen.
- **Arquitectura Escalable y Robusta:** 8 subsistemas desacoplados, modelos Pydantic inmutables (`frozen=True`), persistencia SQLite WAL y **aritmética Decimal pura (cero floats)**.
- **Calidad y Determinismo:** Suite completa de **545 tests unitarios y de integración pasando al 100%**.

---

## 📍 Dónde Estamos (Agosto 2026)

### ✅ Completado al 100%
- **M1: Exchange Configuration & Filters:** `SymbolFilters`, validación de `LOT_SIZE`, `PRICE_FILTER`, `MIN_NOTIONAL`.
- **M2: API Client & Rate Limiter:** Token Bucket (1200 weight/min), HMAC-SHA256, exponential backoff.
- **M3: Grid State Manager:** Persistencia SQLite transaccional ACID, reconciliación automática de órdenes.
- **M4: Order Execution & Lifecycle:** Ejecución, cancelación y seguimiento de órdenes.
- **M5: Grid Engine (Core):** Cálculo de niveles, distribución de capital y ciclo buy/sell.
- **M6: Grid Backtesting Engine:** Simulación histórica offline con cálculo de Sortino, Calmar y Max Drawdown.
- **M7: Bot Orchestrator, CLI & Web:** CLI Click multi-comando, servidor Web FastAPI y panel de control.
- **M9: Quantitative Strategies & Paper Trading:** Formulación matemática RSI Divergence + EMA 200 + ATR Risk para cuentas de $25 USD.

---

## 📂 Estructura de Documentación

Al iniciar sesión, consulta los documentos en este orden:

1. **[INICIO_AQUÍ.md](file:///c:/Users/merid/Downloads/chim/documentado/INICIO_AQUÍ.md)** (este archivo) — Resumen de 2 minutos.
2. **[PROJECT_STATUS.md](file:///c:/Users/merid/Downloads/chim/documentado/PROJECT_STATUS.md)** — Matriz detallada del estado técnico y operativo.
3. **[M9_QUANTITATIVE_STRATEGIES_AND_BACKTESTING.md](file:///c:/Users/merid/Downloads/chim/documentado/M9_QUANTITATIVE_STRATEGIES_AND_BACKTESTING.md)** — Formulación matemática de estrategias y Paper Trading ($25 USD).
4. **[ROADMAP.md](file:///c:/Users/merid/Downloads/chim/documentado/ROADMAP.md)** — Hoja de ruta y fases de despliegue futuro.
5. **[INDEX.md](file:///c:/Users/merid/Downloads/chim/documentado/INDEX.md)** — Índice maestro de archivos.

---

## 🎯 Objetivo Financiero M9 ($25 USD)

```
  Capital Inicial: $25.00 USDT  -->  Target Neto: +$5.00 USDT (+20% ROI en <= 30 días)
  Riesgo por Operación: 2.5%    -->  Ratio Riesgo:Beneficio: 1 : 2.50
  Max Drawdown Permitido: <= 8.00% ($2.00 USD)
```

---

## 🔐 Principios Innegociables

1. **Decimal-Only:** Prohibición estricta de `float` en modelos de precios y dinero.
2. **Testing $\ge 90\%$:** Todo código nuevo debe incluir tests y pasar la suite (545/545 tests actuales).
3. **Inmutabilidad:** Entidades financieras protegidas con `frozen=True`.

---
*Chimuelo Prime — Sistema de Trading Cuantitativo Automatizado.*
