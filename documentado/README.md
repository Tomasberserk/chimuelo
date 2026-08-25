# Chimuelo Prime — Algorithmic & Quantitative Trading System

**v1.0.0** | Sistema de Trading Automatizado de Alta Precisión para Binance Spot.

---

## 🎯 ¿Qué es Chimuelo Prime?

Chimuelo Prime es una plataforma integral de trading algorítmico y cuantitativo desarrollada en Python con arquitectura desacoplada, diseño orientado al dominio y determinismo financiero estricto.

El sistema soporta dos motores de ejecución complementarios:
1. **Grid Engine de Doble Régimen:** Trading en rangos para activos estructurales (SOL/USDT) y caóticos (DOGE/USDT).
2. **Quantitative Signal & Alpha Engine (M9):** Estrategia direccional de reversión por divergencias RSI filtradas por tendencia y volumen, con dimensionamiento optimizado para micro-cuentas de **$25 USD**.

---

## 🚀 Inicio Rápido

```bash
# 1. Clonar el repositorio
git clone <repo-url> chimuelo_prime
cd chimuelo_prime

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Ejecutar la suite de pruebas
pytest tests/ -q
# Output: 545 passed in ~12s

# 4. Consultar la documentación oficial
cat documentado/INICIO_AQUÍ.md
cat documentado/PROJECT_STATUS.md
cat documentado/M9_QUANTITATIVE_STRATEGIES_AND_BACKTESTING.md
```

---

## 📂 Arquitectura Modular

```
chimuelo_prime/
├── chimuelo_prime/
│   ├── exchange_config/       # M1: Filtros de exchange y validaciones Decimal
│   ├── api_client/           # M2: Cliente HTTP autenticado con Rate Limiter
│   ├── grid_state/           # M3: Persistencia SQLite ACID y reconciliación
│   ├── order_execution/      # M4: Colocación y ciclo de vida de órdenes
│   ├── grid_engine/          # M5: Lógica central de Grid Trading
│   ├── backtesting/          # M6 & M9: Motores de backtesting y simulación
│   ├── orchestrator/         # M7: Orquestador multi-hilo, CLI Click y Web Server
│   └── strategies/           # M9: Estrategias cuantitativas (RSI Divergence)
│
├── tests/                    # Suite de 545 pruebas unitarias y de integración
└── documentado/              # Documentación técnica exhaustiva
    ├── INICIO_AQUÍ.md
    ├── PROJECT_STATUS.md
    ├── M9_QUANTITATIVE_STRATEGIES_AND_BACKTESTING.md
    ├── ROADMAP.md
    ├── INDEX.md
    ├── MARTA.md
    └── EDISON.md
```

---

## 🔐 Principios Innegociables

- **Decimal-Only:** Prohibición absoluta de números de coma flotante (`float`) en modelos y cálculos financieros.
- **Testing Exhaustivo:** Cobertura de pruebas $\ge 90\%$ (100% de tests passing).
- **Control Riguroso de Riesgo:** Circuit Breakers intra-diarios (-4%), de portafolio (-8%) y Stop Loss dinámico vía ATR 14.

---
*Chimuelo Prime — Desarrollado por el Swarm de Arquitectura y Desarrollo.*
