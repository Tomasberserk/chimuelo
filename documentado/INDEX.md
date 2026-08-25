# 📚 ÍNDICE COMPLETO — Documentación de Chimuelo Prime

## 🎯 Entrada Rápida (Lee Primero)

👉 **¿Eres nuevo en el proyecto o inicias sesión?** Comienza aquí:
1. [`INICIO_AQUÍ.md`](file:///c:/Users/merid/Downloads/chim/documentado/INICIO_AQUÍ.md) — contexto de 2 minutos + qué hacer ahora.
2. [`PROJECT_STATUS.md`](file:///c:/Users/merid/Downloads/chim/documentado/PROJECT_STATUS.md) — estado actual consolidado (100% módulos operativos, 545 tests).
3. [`M9_QUANTITATIVE_STRATEGIES_AND_BACKTESTING.md`](file:///c:/Users/merid/Downloads/chim/documentado/M9_QUANTITATIVE_STRATEGIES_AND_BACKTESTING.md) — especificación formal de estrategias y paper trading para $25 USD.

---

## 📂 Mapeo de Documentos

### 🚀 [INICIO_AQUÍ.md](file:///c:/Users/merid/Downloads/chim/documentado/INICIO_AQUÍ.md)
- Resumen ejecutivo de qué es Chimuelo Prime.
- Estado global de arquitectura y suite de pruebas (545/545 tests passing).
- Instrucciones de arranque rápido según tu rol.

### 📊 [PROJECT_STATUS.md](file:///c:/Users/merid/Downloads/chim/documentado/PROJECT_STATUS.md)
- Matriz detallada de estado de todos los módulos (M1 a M7 y M9).
- Métricas de calidad, cobertura de código y mitigación de deuda técnica.
- Protocolos de validación y próximos pasos en Testnet / Live Paper Trading.

### 📈 [M9_QUANTITATIVE_STRATEGIES_AND_BACKTESTING.md](file:///c:/Users/merid/Downloads/chim/documentado/M9_QUANTITATIVE_STRATEGIES_AND_BACKTESTING.md)
- Formulación matemática de la estrategia **RSI Divergence + EMA 200 Trend Filter + Volume Breakout + ATR Risk**.
- Objetivo financiero: **$25.00 USDT $\to$ +$5.00 USDT (+20% ROI) en $\le 30$ días**.
- Arquitectura del motor de backtesting event-driven y broker virtual.
- Protocolo estricto de Money Management adaptado al `MIN_NOTIONAL` de $5.00 USDT en cuentas micro.

### 🗺️ [ROADMAP.md](file:///c:/Users/merid/Downloads/chim/documentado/ROADMAP.md)
- Hoja de ruta completa del ecosistema (M1 a M9).
- Fases de despliegue: Paper Trading Live $\to$ Testnet $\to$ Multi-activo $\to$ Mainnet.

### ⚙️ [MARTA.md](file:///c:/Users/merid/Downloads/chim/documentado/MARTA.md)
- Reglas de auditoría y operación de la Arquitecta en Jefe.
- Principios innegociables: Decimal-only, cobertura $\ge 90\%$, inmutabilidad, cero floats.

### 🔧 [EDISON.md](file:///c:/Users/merid/Downloads/chim/documentado/EDISON.md)
- Guía de desarrollo, stack técnico y checklist de implementación para desarrolladores.

---

## 🔐 Principios Fundacionales del Sistema

1. **Decimal-Only:** Cero floats en cálculos de dinero, precios y cantidades.
2. **Tests Obligatorios $\ge 90\%$:** Todo cambio requiere verificación determinista.
3. **Control Estricto de Riesgo:** Circuit breakers intra-diarios (-4%) y de portafolio (-8%).
4. **Arquitectura Desacoplada:** Principios SOLID, inyección de dependencias e inmutabilidad de datos (`frozen=True`).

---
*Índice oficial mantenido por la Dirección de Documentación Técnica.*
