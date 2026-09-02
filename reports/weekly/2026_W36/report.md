# Chimuelo Prime — Reporte de Auditoría Semanal (2026_W36)

> **ID de Reporte:** `audit_2026_W36_1788383112` | **Schema:** `v1.0.0`  
> **Generado:** `2026-09-02T21:05:12.866664+00:00` | **Git Commit SHA:** `4040a27adfed`  
> **Estrategia:** `v1.0.0-frozen` | **Config Hash:** `12c68c1a40b27329...`  
> **Hash de Integridad (SHA-256):** `1946a275f4cef1491170eabd43b43dac15eecd72c871a5e16b88b979ce94221a`  
> **Data Quality Reconciliation:** `PASS / 0 inconsistencies`  

---

## 1. Resumen de Desempeño y Capital

| Métrica | Valor | Métrica | Valor |
| :--- | :--- | :--- | :--- |
| **Capital Inicial** | \$100.00 USD | **Patrimonio Actual** | \$100.00 USD |
| **High-Water Mark** | \$100.00 USD | **Max Drawdown** | 0.0% |
| **PnL Neto Acumulado** | \$0 USD | **Profit Factor** | 0.0 |
| **Win Rate** | 0.0% (0W / 0L) | **Expectancy** | \$0.0 USD / trade |
| **Average R** | 0.0R | **Median R** | 0.0R |
| **Ganancia Media (Win)** | \$0.0 USD | **Pérdida Media (Loss)** | \$0.0 USD |
| **Mayor Ganancia** | \$0.0 USD | **Mayor Pérdida** | \$0.0 USD |

---

## 2. Reconciliación de Calidad de Datos (Data Quality)

* **Veredicto:** **`PASS`** (0 inconsistencias)
* **Signals $\leftrightarrow$ Orders Reconciled:** `True`
* **Orders $\leftrightarrow$ Fills Reconciled:** `True`
* **Fills $\leftrightarrow$ Positions Reconciled:** `True`
* **Positions $\leftrightarrow$ PnL Reconciled:** `True`
* **Risk Events $\leftrightarrow$ State Reconciled:** `True`
* **Eventos Huérfanos / Missing Fills / IDs Duplicados:** `0 / 0 / 0`

---

## 3. Auditoría de Señales y Riesgo

* **Velas / Barras Evaluadas:** `0`
* **Señales Aprobadas para Ejecución:** `0`
* **Bloqueos por Filtros de Estrategia:** `0`
* **Bloqueos por Risk Engine:** `0`
* **Posiciones Abiertas Actualmente:** `0`

---

## 4. Desempeño por Activo

| Símbolo | Trades | Win Rate | Profit Factor | PnL Neto | Average R |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **BTCUSDT** | 0 | 0.0% | 0.0 | \$0.00 USD | 0.0R |
| **SOLUSDT** | 0 | 0.0% | 0.0 | \$0.00 USD | 0.0R |

---

## 5. Comparativa de Desviación (Drift Tracker vs Backtest)

### A. vs Historical Full-Sample (2024–2026 Walk-Forward)
* **Frecuencia Mensual:** Observada `0.0` vs Esperada `5.63` (Delta: `-5.63`)
* **Profit Factor:** Observado `0.0` vs Esperado `1.03` (Delta: `-1.03`)
* **Win Rate:** Observado `0.0%` vs Esperado `37.04%`
* **Average R:** Observado `0.0R` vs Esperado `0.1R`

### B. vs Historical Out-of-Sample (2022–2024 True Unseen Holdout)
* **Profit Factor:** Observado `0.0` vs Esperado `1.16` (Delta: `-1.16`)
* **Win Rate:** Observado `0.0%` vs Esperado `41.62%`
* **Average R:** Observado `0.0R` vs Esperado `0.26R`

---

## 6. Calidad de Ejecución e Infraestructura

* **Slippage Acumulado:** `\$0 USD`
* **Comisiones Simuladas (Fees):** `\$0 USD`
* **Latencia Media:** `0.0 ms`
* **Reconexiones WebSocket:** `0`
* **Fallbacks a REST:** `0`
* **Velas Duplicadas / Stale:** `0 / 0`

---

## 7. Trade Ledger Completo de la Semana

_No se registraron cierres de operaciones durante el período auditado._

---
_Reporte generado automáticamente por el Weekly Audit Reporting System de Chimuelo Prime. Inmutable y reproducible._
