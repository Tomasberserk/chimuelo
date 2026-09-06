# CHIMUELO PRIME — REGIME & STRATEGY ROUTER SPECIFICATION v0.1 (HARDENED)
## Arquitectura Sistemática Multi-Motor, Clasificación Causal de Estado y Asignación de Riesgo

---

## 1. Declaración de Misión y Filosofía Cuantitativa

El objetivo de esta especificación es desacoplar de forma estricta e irreversible cuatro capas independientes:

$$
\boxed{\mathbf{Market\ Regime} \neq \mathbf{Trading\ Signal} \neq \mathbf{Risk\ Decision} \neq \mathbf{Execution}}
$$

$$
\text{Market Data} \longrightarrow \text{Feature Engine} \longrightarrow \text{Regime Engine} \longrightarrow \text{Strategy Router} \longrightarrow \text{Risk Allocator} \longrightarrow \text{Execution}
$$

Ninguna estrategia se ejecuta de forma incondicional. Toda operación debe satisfacer el axioma fundamental:

$$
\mathbf{TradeAllowed} = \mathbf{RegimeCompatible} \land \mathbf{StrategyTrigger} \land \mathbf{RiskBudgetAllowed} \land \neg\mathbf{HermesVeto}
$$

> [!IMPORTANT]
> **Aislamiento Estricto de Producción:** La estrategia **Strategy C (v1.0.0-frozen)** en `live_runner.py` permanece 100% congelada, aislada e inalterada durante sus 60 días de Live Paper Trading. Todo el nuevo sistema se desarrolla en submódulos paralelos (`chimuelo_prime/regime_engine/`).

---

## 2. Definición Matemática del Vector de Estado de Mercado ($S_t$)

Para cada vela $t$ cerrada en temporalidad principal ($1\text{h}$) y contexto ($4\text{h}$), el **Feature Engine** calcula el vector de estado compuesto:

$$
S_t = [ \text{Trend}_t, \text{Volatility}_t, \text{Structure}_t, \text{Participation}_t, \text{Derivatives}_t ]
$$

### Dimensión 1: Tendencia (Trend State)
1. **Pendiente de Medias Normalizada (Slope):**
   $$
   Slope_{50,t} = \frac{EMA_{50,t} - EMA_{50,t-20}}{ATR_{20,t}}
   $$
2. **Separación de Tendencia (Trend Spread):**
   $$
   TrendSpread_t = \frac{EMA_{20,t} - EMA_{50,t}}{ATR_{20,t}}
   $$
3. **Fuerza Direccional:** $ADX_{14,t}$.
4. **Clasificación Discreta:**
   * **STRONG_BULL:** $TrendSpread > 1.0 \land ADX > 25 \land Slope_{50} > 0$
   * **BULL:** $TrendSpread > 0.0 \land ADX > 20$
   * **NEUTRAL / CHOP:** $ADX \le 20$
   * **BEAR:** $TrendSpread < 0.0 \land ADX > 20$
   * **STRONG_BEAR:** $TrendSpread < -1.0 \land ADX > 25 \land Slope_{50} < 0$

---

### Dimensión 2: Volatilidad (Volatility State)
1. **Rango Verdadero Medio (ATR) y Volatilidad Realizada (RV):**
   $$
   RV_{n,t} = \sqrt{\sum_{i=0}^{n-1} \ln\left(\frac{C_{t-i}}{C_{t-i-1}}\right)^2}
   $$
2. **Percentiles Rodantes estrictamente causales (Ventana $W=500$ barras):**
   $$
   ATRRank_t = P_{500}(ATR_{20,t}), \quad RVRank_t = P_{500}(RV_{20,t})
   $$
   *(Prohibido el uso de percentiles globales o futuros para evitar Data Leakage).*
3. **Clasificación Discreta:**
   * **EXTREME_COMPRESSION:** $ATRRank < 10$
   * **COMPRESSION:** $10 \le ATRRank < 25$
   * **NORMAL_VOLATILITY:** $25 \le ATRRank \le 75$
   * **EXPANSION:** $75 < ATRRank \le 90$
   * **EXTREME_EXPANSION:** $ATRRank > 90$

---

### Dimensión 3: Estructura de Mercado y Rango (Market Structure)
1. **Efficiency Ratio de Kaufman ($ER_{20}$):**
   $$
   ER_{20,t} = \frac{|C_t - C_{t-20}|}{\sum_{i=1}^{20} |C_i - C_{i-1}|}
   $$
   * $ER \to 1.0$: Desplazamiento limpio, direccional y eficiente.
   * $ER \to 0.0$: Ruido browniano, mercado en rango y absorción sin avance neto.
2. **Clasificación Discreta:**
   * **DIRECTIONAL:** $ER \ge 0.60$
   * **TRANSITIONAL:** $0.35 \le ER < 0.60$
   * **RANGE_BOUND:** $ER < 0.35$

---

### Dimensión 4: Participación de Volumen (Participation State)
*(Nombrado `Participation` en vez de `Liquidity` ya que mide volumen y rango transaccionado, no profundidad de Order Book L2/L3).*
1. **Percentil de Volumen rodante ($W=200$ barras):**
   $$
   VolumeRank_t = P_{200}(Volume_t)
   $$
2. **Percentil de Rango Verdadero rodante:**
   $$
   TRRank_t = P_{200}(TR_t)
   $$
3. **Clasificación Discreta:**
   * **NORMAL_PARTICIPATION:** $VolumeRank < 70$
   * **PARTICIPATION_EXPANSION:** $VolumeRank \ge 70$
   * **VOLUME_SHOCK:** $VolumeRank \ge 90 \land TRRank \ge 90$

---

### Dimensión 5: Capa de Derivados (Derivatives State — BTC / ETH / SOL)
1. **Funding Acumulado de 8 Horas y Z-Score ($W=720$ barras):**
   $$
   Z_{Funding,t} = \frac{F_{8h,t} - \mu_{F,720}}{\sigma_{F,720}}
   $$
2. **Contracción / Expansión de Interés Abierto (Open Interest):**
   $$
   \Delta OI_{4h,t} = \frac{OI_t - OI_{t-4}}{OI_{t-4}}
   $$
3. **Clasificación Discreta con Separación Causal:**
   * **EXTREME_CROWDED_LONG:** $Z_{Funding} > +2.0 \land \Delta OI_{4h} > +5\%$
   * **EXTREME_CROWDED_SHORT:** $Z_{Funding} < -2.0 \land \Delta OI_{4h} > +5\%$
   * **DERIVATIVES_STRESS:** $|Z_{Funding}| > 2.0 \land \Delta OI_{4h} < -5\% \land VolumeRank \ge 90$
   * **FORCED_DELEVERAGING_CONFIRMED:** Requiere confirmación por feed de liquidaciones simultáneas en el exchange.
   * **NEUTRAL_DERIVATIVES:** $|Z_{Funding}| \le 1.0$

---

## 3. Máquina de Estados Finita (FSM) y Desacoplamiento ARMED / ACTIVE

La compatibilidad de régimen **no genera órdenes**; únicamente otorga permiso de vigilancia:

```
                ┌──────────────┐
                │   DISABLED   │
                └──────┬───────┘
                       │
                 Score ≥ 0.70 (y Ambiguity Gate superado)
                       │
                       ▼
                ┌──────────────┐
                │    ARMED     │◄───┐
                └──────┬───────┘    │  (Score se mantiene ≥ 0.45)
                       │            │  (Histéresis)
               Alpha Trigger        │
                       │            │
                       ▼            │
                ┌──────────────┐    │
                │    ACTIVE    │────┘
                └──────┬───────┘
                       │
                  Exit Event
                       │
                       ▼
                ┌──────────────┐
                │   COOLDOWN   │
                └──────┬───────┘
                       │
                  Cooldown_Bars = 0
                       │
                       ▼
                ┌──────────────┐
                │   DISABLED   │
                └──────────────┘
```

### Reglas de Estado:
1. **`ARMED` (Armada):** El régimen es propicio ($Score_s \ge 0.70$). La estrategia monitorea cada barra en busca de su gatillo de entrada.
2. **`ACTIVE` (En Posición):** El Alpha Engine detectó el gatillo técnico y el Risk Allocator aprobó la orden.
3. **`COOLDOWN` (Enfriamiento Obligatorio):** Tras cerrar una posición, la estrategia queda bloqueada durante $N$ velas para evitar reentradas compulsivas:
   * **Estrategia A:** $4$ velas ($1\text{h}$).
   * **Estrategia B:** $4$ velas ($15\text{m}$).
   * **Estrategia C:** $6$ velas ($1\text{h}$).
   * **Estrategia D:** $8$ velas ($15\text{m}$).
4. **Histéresis Anti-Flapping:** Una vez armada, permanece armada mientras $Score_s \ge 0.45$. Si cae por debajo de $0.45$, pasa a `DISABLED`.

---

## 4. Filtro de Ambigüedad y Régimen "NO TRADE" (Flat)

Para evitar operar en mercados confusos donde múltiples estrategias tienen puntuaciones medias idénticas:

$$
\text{RegimeConfidence} = Score_{max} - Score_{second}
$$

El Router declara **`CHIMUELO_MODE = 100%_CASH`** si:
1. $\max(Score_A, Score_B, Score_C, Score_D) < 0.40$, **O**
2. $\text{RegimeConfidence} < 0.15$ (mercado ambiguo sin ventaja clara), **O**
3. $\text{HermesVeto} == \text{True}$.

---

## 5. Asignador de Riesgo y Correlation Gate de Dos Niveles

El riesgo no es fijo. Se parametriza dinámicamente:
* $R_{trade,max} = 0.50\%$ NAV.
* $R_{portfolio,max} = 1.50\%$ NAV.
* Cada operación recibe un riesgo objetivo $R_i \in [0.15\%, 0.50\%]$ en función del score de régimen y la volatilidad.

### Nivel 1 — Exact Exposure Gate (Mismo activo + misma dirección)
Si dos estrategias armadas disparan compras simultáneas en el mismo par (ej. Breakout + Pullback en SOL):
$$
Risk_{total,SOL} \le 0.50\% \implies Risk_A = 0.30\%, \quad Risk_B = 0.20\%
$$

### Nivel 2 — Factor Correlation Gate (Cluster Beta)
Se calcula la correlación rodante de retornos ($W=100$ barras):
$$
\rho_{ij} = \text{Corr}(r_i, r_j)
$$
Si $\rho_{ij} > 0.70$ (ej. BTC, ETH y SOL altamente acoplados en una subida beta):
$$
Risk_{cluster} \le 0.75\% \text{ NAV}
$$
Se impide que tres señales aparentemente independientes acumulen un riesgo acumulado no diversificado.

---

## 6. Sincronización Temporal Causal y Warmup Dinámico

1. **Sincronización 1h / 4h (Cero Look-Ahead):**
   A las `10:00 1h`, el contexto macro 4h utiliza estrictamente la **última vela 4h cerrada** (la de las `08:00`). Nunca se lee la vela 4h en curso.
2. **Causalidad de Derivados:**
   $Z_{Funding}(t)$ y $\Delta OI(t)$ se computan con las observaciones disponibles inmediatamente antes del cierre de la vela $t$.
3. **`FeatureWarmupPolicy` Dinámico:**
   $$
   WarmupRequired = \max(W_{ATRRank}, W_{ZFunding}, W_{VolumeRank}, W_{EMA}) + 50 = \max(500, 720, 200, 200) + 50 = 770 \text{ barras}
   $$

---

## 7. Registro Forense Integral (Decisiones Positivas y Negativas)

El `ForensicLogger` no registra únicamente operaciones ejecutadas. Registra **todas las evaluaciones horarias**, incluyendo los motivos de abstención:

```json
{
  "timestamp": "2026-09-06T14:00:00Z",
  "symbol": "BTCUSDT",
  "regime_scores": {"A": 0.81, "B": 0.32, "C": 0.15, "D": 0.20},
  "fsm_states": {"A": "ARMED", "B": "DISABLED", "C": "DISABLED", "D": "DISABLED"},
  "alpha_trigger": false,
  "action": "NO_TRADE",
  "block_reason": "NO_TRIGGER",
  "regime_vector": {
    "trend": "STRONG_BULL",
    "volatility": "EXPANSION",
    "efficiency_ratio": 0.72,
    "participation": "PARTICIPATION_EXPANSION",
    "derivatives": "NEUTRAL"
  }
}
```

---

## 8. El Rol Estricto de Hermes: Veto Exclusivo

$$
\mathbf{HermesVeto} \in \{\text{True}, \text{False}\}
$$
* Hermes puede **bloquear** entradas si detecta eventos macroeconómicos adversos, anomalías de API o noticias geopolíticas de alto impacto.
* **Prohibición Arquitectónica:** Hermes jamás puede emitir una orden de compra o venta por sí mismo. La generación de señales pertenece exclusivamente a los motores matemáticos deterministas.
