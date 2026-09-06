# Bitácora de Estrategias Cuantitativas — Chimuelo Prime
## Arquitectura Multi-Régimen & Hoja de Ruta Sistemática

---

## 1. Filosofía Institucional: Multi-Strategy Regime Allocation

En los mercados cuantitativos de criptomonedas, **ninguna estrategia individual tiene un *edge* permanente en todos los estados del mercado**. 
* Una estrategia de **Breakouts** pierde dinero en mercados laterales (falsas rupturas constantes).
* Una estrategia de **Reversión / Grid** se arruina en tendencias verticales sin retrocesos.
* Una estrategia de **Pullbacks** se queda inactiva cuando el mercado sube en línea recta sin retroceder.

El objetivo del repositorio de estrategias es disponer de un catálogo de **arquetipos matemáticos no correlacionados**, donde cada una tenga un cometido específico y reglas de invalidación precisas.

---

## 2. Taxonomía de los 5 Estados del Mercado en Cripto

| Régimen | Características Técnicas | Métrica / Indicador Sensor | Arquetipo de Estrategia |
| :--- | :--- | :--- | :--- |
| **Régimen 1: Expansión Tendencial (Bull / Bear Run)** | Ruptura de rangos, volumen creciente, velas direccionales continuas. | ADX(14) > 25, Donchian High/Low roto, Volumen > P70, Precio fuera de Bandas Bollinger. | **Trend-Following Breakout** (Ej. *Strategy C*) |
| **Régimen 2: Retroceso en Tendencia (Pullback / Dip)** | Movimiento correctivo ordenado hacia medias móviles institucionales sin romper estructura macro. | Precio > EMA 100/200, RSI(14) < 38 o estocástico sobrevendido, ATR comprimido. | **Trend Continuation / Dip-Buying** (Ej. *RSI Divergence Chimuelo*) |
| **Régimen 3: Compresión y Rango Lateral (Range-Bound)** | Máximos y mínimos acotados, volumen decreciente, osciladores rebotando en niveles medios. | Choppiness Index > 61.8, Bandas Bollinger comprimidas (Squeeze), ADX < 20. | **Mean Reversion / Neutral Grid Trading** |
| **Régimen 4: Clímax y Barrido de Liquidez (Liquidity Sweep)** | Movimiento parabólico violento, liquidación masiva de cortos/largos, divergencia en Open Interest. | Funding Rate extremo (>0.05% o <-0.05%), Mecha de absorción > 60% del rango, Volumen P95+. | **Fade the Climax / Stop-Run Reversal** |
| **Régimen 5: Mercado Tóxico / Caótico (Whipsaw)** | Movimientos erráticos sin dirección, noticias macro inminentes (FOMC, CPI), spread abierto. | ATR spike sin volumen spot, correlación BTC/Altcoins rota, alta latencia. | **100% Cash / Modo Espera (Capital Preservation)** |

---

## 3. Catálogo Canónico de Estrategias para Chimuelo

### Estrategia A: Structural Breakout (Strategy C — Activa en Paper Trading)
* **Objetivo:** Capturar el inicio de tendencias fuertes y expansiones de volatilidad.
* **Reglas Clave:** Ruptura de Donchian 20 barras + Volumen P70 + Vela cerrando en el tercio superior + BTC diario D-1 alcista.
* **Target Timeframe:** 1h.
* **Ratio Riesgo/Beneficio:** R:R $\ge 2.2$.

### Estrategia B: Deep Pullback RSI Divergence (Strategy Chimuelo MVP)
* **Objetivo:** Comprar en descuentos profundos dentro de una tendencia macro consolidada.
* **Reglas Clave:** Precio > EMA 200 + RSI(14) < 38 + Divergencia alcista regular confirmada con volumen de absorción.
* **Target Timeframe:** 1h.
* **Ratio Riesgo/Beneficio:** R:R $\ge 2.5$.

### Estrategia C: Volatility Squeeze & Expansion (Keltner-Bollinger Squeeze)
* **Objetivo:** Identificar cuando el mercado duerme (compresión de volatilidad) y disparar en la dirección de la primera barra de expansión.
* **Reglas Clave:** Bandas de Bollinger dentro de Canales de Keltner por $\ge 6$ barras; gatillo en la primera vela que cierra fuera de Keltner con volumen $\ge 1.5\times$ SMA(20).
* **Target Timeframe:** 1h / 4h.
* **Ratio Riesgo/Beneficio:** R:R $\ge 2.0$.

### Estrategia D: Liquidity Sweep & Rejection (Order Block / Mechas de Absorción)
* **Objetivo:** Operar trampas de mercado donde los creadores de mercado inducen roturas de soporte/resistencia para cazar stops institucionales.
* **Reglas Clave:** El precio perfora el mínimo/máximo de las últimas 24 horas pero la vela cierra **dentro** del rango anterior dejando una mecha $\ge 60\%$ del cuerpo + pico de volumen.
* **Target Timeframe:** 15m / 1h.
* **Ratio Riesgo/Beneficio:** R:R $\ge 3.0$.

### Estrategia E: Adaptive Dynamic Grid (Rango Lateral)
* **Objetivo:** Cosechar micro-fluctuaciones en activos con alta correlación y baja direccionalidad cuando el Choppiness Index sea alto.
* **Reglas Clave:** Límites fijados por $2.5\times$ ATR alrededor del VWAP semanal; rebalanceo automático con take profit en media móvil central.
* **Target Timeframe:** 15m / 1h.

---

## 4. El Rol de "Hermes" (Agente de Contexto y Análisis Cualitativo)

El agente **Hermes** no reemplazará el motor matemático de ejecución; actuará como un **Comité de Riesgos y Enrutamiento Contextual**:

1. **Filtro de Veto Macro:** Si hay un evento de alto impacto inminente (ej. minutas de la Fed, datos de inflación de EE.UU.), Hermes activa el estado de *Veto* forzando a todas las estrategias a suspender nuevas entradas.
2. **Selector de Sesgo (Regime Bias):** Si el sentimiento on-chain o las tasas de fondeo muestran una euforia excesiva (FOMO extremo), Hermes instruye al enrutador a desactivar compras de Breakout por riesgo de trampa alcista y habilitar estrategias de retroceso o tomas de beneficio ajustadas.
3. **Ponderación de Capital:** Asigna mayor presupuesto de riesgo a la estrategia cuya tesis concuerde con el entorno de mercado actual.

---

## 5. Prompt Maestro para ChatGPT: Investigación y Diseño de Estrategias

*(Copia y pega este prompt directamente en ChatGPT para generar y calibrar nuevas estrategias con rigor cuantitativo).*

```markdown
Actúa como un Diseñador Cuantitativo Senior y Arquitecto de Estrategias Algorítmicas para fondos de trading sistemático en criptomonedas.

Estoy construyendo un ecosistema multi-estrategia llamado "Chimuelo Prime" para operar en spot/futuros de Binance (BTCUSDT, SOLUSDT, ETHUSDT) en temporalidades de 1h y 15m.

Quiero diseñar una bitácora de estrategias sistemáticas robustas y no correlacionadas. Por favor, no me des conceptos vagos de retail (como "cruces de medias simples" o "indicadores mágicos"). Requiero especificaciones cuantitativas formales basadas en edge matemático comprobable.

Para cada una de las estrategias que propongas, debes detallar la siguiente ficha técnica obligatoria:

1. NOMBRE Y FILOSOFÍA DEL EDGE:
   - ¿Por qué existe esta anomalía en el mercado cripto? (Ineficiencias de liquidez, comportamiento de derivados, liquidaciones, seguimiento de tendencia).
   - Régimen de mercado óptimo (Tendencia alcista, retroceso, compresión lateral, o clímax/agotamiento).

2. ACTIVOS Y TIMEFRAME:
   - Timeframe principal y timeframe de confirmación macro (ej. 1h gatillo / 1d contexto).

3. REGLAS DE ENTRADA CUANTITATIVAS (MATEMÁTICA PURA):
   - Definición exacta de indicadores (fórmulas, periodos exactos, no ambiguos).
   - Filtro de tendencia / régimen (Gate 1).
   - Filtro de volumen / volatilidad (Gate 2, ej. percentiles P70/P90 o múltiplos de ATR/SMA).
   - Condición de gatillo exacta al cierre de la vela (Gate 3).

4. GESTIÓN DE RIESGO Y SALIDA ESTRICTA:
   - Ubicación exacta del Stop Loss (basado en estructura de mercado o múltiplos de ATR, nunca en pips arbitrarios).
   - Ubicación del Take Profit (definición del ratio R:R mínimo, típicamente >= 2.0R).
   - Regla de invalidación prematura (si aplica).

5. CUÁNDO FALLA ESTA ESTRATEGIA (PUNTO CIEGO):
   - ¿Bajo qué condiciones de mercado pierde dinero consistentemente?
   - ¿Qué filtro o sensor cuantitativo previene que opere en ese entorno desfavorable?

Por favor, inicia proponiendo 4 estrategias altamente diferenciadas entre sí que cubran:
A) Ruptura por Expansión de Volatilidad (Volatility Squeeze Breakout).
B) Compra de Retroceso Profundo con Absorción de Volumen (Deep Pullback / Volume Absorption).
C) Reversión por Barrido de Liquidez / Falso Rompimiento (Liquidity Sweep Fade).
D) Explotación de Derivados / Tasa de Fondeo y Clímax (Funding Rate & Open Interest Exhaustion).
```
