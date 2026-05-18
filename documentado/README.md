# Chimuelo Prime — Grid Trading Bot para Binance

**v0.1.0-dev** | Desarrollo iterativo, bloqueante, cero deuda técnica.

---

## ¿Qué es Chimuelo Prime?

Bot de grid trading automatizado para Binance Testnet/Mainnet con:
- **Estrategia diversificada:** activos de volatilidad estructural (SOL/USDT) + caótica (DOGE/USDT).
- **Gestión rigurosa de riesgo:** circuit breakers, drawdown limits, ruptura de régimen.
- **Arquitectura escalable:** 7 módulos independientes, inyección de dependencias, cero floats en dinero.
- **Procesos disciplinados:** auditoría de código línea por línea, tests ≥ 90%, iterativo, bloqueante.

---

## 🚀 Inicio Rápido

### 1. Clonar y Setup

```bash
git clone <repo-url> chimuelo_prime
cd chimuelo_prime

# Instalar dependencias
pip install -r requirements.txt --break-system-packages

# Leer documentación de contexto (2 minutos)
cat docs/INICIO_AQUÍ.md
```

### 2. Determina tu Rol y Qué Hacer

```bash
# Lee según tu rol:
cat docs/INICIO_AQUÍ.md      # Todos: contexto general (2 min)
cat docs/PROJECT_STATUS.md   # Todos: estado actual (15 min)

# Luego, según TU rol:
cat docs/MARTA.md     # Si eres Marta (Arquitecta)
cat docs/EDISON.md    # Si eres Edison (Programador)
cat docs/ROADMAP.md   # Si eres Tom o necesitas ver el futuro (20 min)
```

### 3. Ejecuta tu Tarea

Ver `docs/PROJECT_STATUS.md` → sección "Trabajo en Progreso" para la tarea actual.

Actualmente: **Edison ejecutando Tarea #2 del Módulo 1** (suite de tests).

---

## 📂 Estructura del Proyecto

```
chimuelo_prime/
├── chimuelo_prime/               # Código fuente
│   └── exchange_config/          # M1: Exchange Filters (✅ 20% done)
│       ├── __init__.py
│       ├── exceptions.py         # ✅ Jerarquía tipificada
│       ├── models.py             # ✅ SymbolFilters + SymbolConfig
│       ├── client.py             # ⏸️ TODO: cliente HTTP
│       ├── service.py            # ⏸️ TODO: fachada pública
│       └── config_loader.py      # ⏸️ TODO: parser de YAML
│
├── tests/                        # Suite de tests
│   └── exchange_config/
│       ├── test_models.py        # ⏸️ TODO: tests para M1
│       ├── test_exceptions.py    # ⏸️ TODO
│       ├── test_config_loader.py # ⏸️ TODO
│       └── fixtures/
│           └── exchange_info_solusdt.json  # Real Binance response
│
├── docs/                         # Documentación (LEER PRIMERO)
│   ├── INICIO_AQUÍ.md           # ✅ Entry point (2 min read)
│   ├── PROJECT_STATUS.md        # ✅ Estado actual detallado
│   ├── MARTA.md                 # ✅ Configuración de Marta
│   ├── EDISON.md                # ✅ Configuración de Edison
│   ├── ROADMAP.md               # ✅ Hoja de ruta M1-M7
│   ├── INDEX.md                 # ✅ Mapa de toda la doc
│   └── specs/
│       └── M1_SPEC.md           # ✅ Especificación completa de M1
│
├── config/
│   └── chimuelo.yaml            # Configuración (símbolos, límites, etc.)
│
├── requirements.txt             # ✅ Dependencias (pinned versions)
└── README.md                    # Este archivo
```

---

## 📖 Documentación Clave

| Documento | Duración | Para Quién | Qué Contiene |
|-----------|----------|-----------|-------------|
| **INICIO_AQUÍ.md** | 2-5 min | Todos | Contexto rápido + qué hacer ahora |
| **PROJECT_STATUS.md** | 10-15 min | Todos | Estado actual detallado, próximos pasos |
| **MARTA.md** | 8-10 min | Marta/Edison | Reglas de operación, auditoría, decisiones |
| **EDISON.md** | 10-12 min | Edison/Marta | Stack, testing, checklist pre-entrega |
| **ROADMAP.md** | 15-20 min | Todos | M1-M7, timeline, features, testing |
| **INDEX.md** | 5 min | Todos | Mapa de navegación de la documentación |
| **M1_SPEC.md** | 20-25 min | Edison/Marta | Especificación técnica detallada de M1 |

**👉 Comienza por:** `docs/INICIO_AQUÍ.md`

---

## 🎯 Estado Actual (18 mayo 2026)

### ✅ Completado
- Parametrización matemática (SOL/USDT validado, ATR, límites, spacing).
- Arquitectura de 7 módulos definida.
- Módulo 1 especificado (11 secciones).
- M1 Tarea #1: `models.py`, `exceptions.py`, `requirements.txt` (✅ done).
- Documentación de agentes (MARTA.md, EDISON.md).

### 🔄 En Progreso
- **Tarea #2 (Edison):** suite de tests para M1 (pytest, responses, coverage ≥ 90%).

### ⏸️ Bloqueado
- M2-M7 esperando M1 al 100%.

**Próximo:** Edison entrega Tarea #2 → Marta audita → merge a develop.

---

## 🔧 Stack Técnico

| Categoría | Herramienta | Versión | Por Qué |
|-----------|-------------|---------|---------|
| **Validación** | Pydantic | 2.9.2 | Strict validation, Decimal-aware |
| **Logging** | structlog | 24.4.0 | JSON nativo, contexto estructurado |
| **Config** | PyYAML | 6.0.2 | Estándar de facto |
| **HTTP** | requests | 2.32.3 | Simple, sync (suficiente para testnet) |
| **Testing** | pytest | 8.3.3 | Estándar, powerful fixtures |
| **Mocks** | responses | 0.25.3 | Mockea HTTP sin servidor |
| **Typing** | mypy | 1.11.2 | Type checking estricto |
| **Linting** | ruff | 0.6.9 | Linter + formatter ultra-rápido |

---

## 🎓 Principios Clave (Nunca Olvides)

1. **Decimal-Only:** Cero floats en cálculos financieros. Binance rechaza con código -1013.
2. **Tests Obligatorios:** ≥ 90% de cobertura. Sin tests = sin merge.
3. **Especificación Primero:** Edison pregunta antes de decidir, nunca adivina.
4. **Bloqueante:** M(n) NO inicia hasta M(n-1) está 100% con Definition of Done cumplido.
5. **Auditoría de Marta:** Cada entregable es auditado línea por línea. Aprobación formal.

---

## 🚀 Próximas Tareas

### Corto plazo (esta semana)
- [ ] Edison: Tarea #2 (tests de M1) — ¿Hoy/mañana?
- [ ] Marta: Audita Tarea #2.
- [ ] Edison: Tarea #3 (cliente HTTP + servicio) si T#2 aprobado.

### Mediano plazo (próximas 2-3 semanas)
- [ ] M1 completado y merged a develop.
- [ ] M2-M3 en desarrollo.
- [ ] Backtesting de parámetros iniciales (Sortino > 1.5, Calmar > 1.0).

### Largo plazo (4-8 semanas)
- [ ] Todos los 7 módulos implementados.
- [ ] Testnet operational (bot running 72+ horas sin intervención).
- [ ] Multi-activo (SOL + DOGE) operando con risk parity.

---

## 📊 Cómo Medir el Progreso

**Por Módulo:**
- Definition of Done ✅
- Tests ≥ 90% coverage ✅
- mypy --strict OK ✅
- ruff check + format OK ✅
- Aprobación formal de Marta ✅

**Global:**
- Backtesting: Sortino > 1.5, Calmar > 1.0, Profit Factor > 1.5.
- Testnet: Bot operando > 72h sin intervención.
- Producción: Multi-activo balanceado por risk parity.

---

## 💬 Cómo Comunicarte

### Edison → Marta
- **Ambigüedad:** *"El spec no aclara X. Interpretación: Y. ¿Correcta?"*
- **Entrega:** *"Módulo X done. Tests 93%, mypy OK. Decidí A en lugar de B. PR abierto."*
- **Bloqueado:** *"Identifico falla: si [escenario], causa [impacto]. Propongo [mitigación]."*

### Tom → Marta
- **Propuesta:** Especifica el cambio y justifica con datos.
- Marta responde con critical flaw analysis.

### Marta → Todos
- **Rechazo:** *"No resiste escrutinio. Rechazado. Motivo: [técnico]. Reintentar con [mitigación]."*
- **Aprobación:** *"Aprobado formalmente. [Observaciones]. Procede a [siguiente fase]."*

---

## 🔐 Cómo Protegemos la Calidad

1. **Especificación detallada antes de código.**
2. **Tests desde el primer commit** (TDD mindset).
3. **Auditoría de Marta línea por línea** antes de merge.
4. **Cero deuda técnica:** si hay, se detiene todo para resolver.
5. **Versionado y tagging:** cada módulo recibe tag `v0.M.0`.
6. **Documentación actualizada:** siempre en sync con código.

---

## ❓ Preguntas Rápidas

**P: ¿Dónde empiezo?**
A: Abre `docs/INICIO_AQUÍ.md`.

**P: ¿Cuál es mi tarea?**
A: Lee `docs/PROJECT_STATUS.md` → "Trabajo en Progreso".

**P: ¿Bloqueado?**
A: Escala a Marta. Ver `docs/MARTA.md` → "Escalación".

**P: ¿Cambio de requisitos?**
A: Propón a Marta. Ella audita con critical flaw analysis.

**P: ¿Cuándo mergeamos?**
A: Solo si Definition of Done 100% cumplida + aprobación de Marta.

---

## 📚 Recursos Externos

- **Binance API Docs:** https://binance-docs.github.io/apidocs/
- **Pydantic:** https://docs.pydantic.dev/
- **pytest:** https://docs.pytest.org/
- **vectorbt (backtesting):** https://vectorbt.dev/

---

## 📝 Historial de Cambios

| Fecha | Qué | Owner |
|-------|-----|-------|
| 17-18 mayo | Parametrización matemática SOL/USDT | Tom + Marta |
| 18 mayo 02:00 | Especificación M1 + modelos | Marta + Edison |
| 18 mayo 02:30 | Documentación de agentes + setup | Tom + Marta + Edison |

---

## 🎯 Visión

**Chimuelo Prime v0.1.0:** Bot de grid trading profesional, auditable, mantenible, escalable. Lanzamiento testnet en 3-4 semanas. Mainnet posteriormente con capital real mínimo.

**Chimuelo Prime v0.2.0+:** Multi-activo, backtesting avanzado, risk parity dinámico, integración con más exchanges.

---

## 📞 Contacto

- **Tom (PM):** propuestas, priorización, decisiones estratégicas.
- **Marta (Arquitecta):** auditoría, decisiones técnicas, escalación.
- **Edison (Programador):** implementación, testing, documentación.

---

**Estado:** En desarrollo activo ✅
**Última actualización:** 18 mayo 2026 02:50 UTC
**Próxima sesión:** Cuando Edison entregue Tarea #2

---

**Comienza por:** `docs/INICIO_AQUÍ.md` (2 minutos)
