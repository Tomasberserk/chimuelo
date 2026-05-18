# 🚀 INICIO AQUÍ — Chimuelo Prime Session Launcher

**¿Eres Tom, Marta o Edison en una nueva sesión?** Lee esto primero (2 minutos).

---

## ¿Qué es Chimuelo Prime?

**Bot de grid trading automatizado para Binance**, enfocado en estrategia diversificada con gestión rigurosa de riesgo y arquitectura escalable. Desarrollo iterativo, bloqueante, cero deuda técnica.

**Stack:** Python (Pydantic, structlog, pytest, requests), SQLite, Binance API.

---

## 📍 Dónde Estamos (18 mayo 2026)

### ✅ Completado
- **Parametrización matemática:** SOL/USDT validado (90 días, ATR diario, límites, spacing, capital).
- **Arquitectura diseñada:** 7 módulos, dependencies, principios SOLID.
- **Módulo 1 (M1) especificado:** 11 secciones de especificación técnica.
- **M1 Tarea #1 entregada:** `models.py`, `exceptions.py`, `requirements.txt`, smoke-test pasando.

### 🔄 En Progreso
- **M1 Tarea #2:** suite de tests (pytest, responses) — **Edison ejecutando ahora**.
- **Bloqueado:** M2-M7 esperando M1 al 100%.

---

## 📂 Estructura de Documentación

Cuando inicies sesión, carga **en este orden:**

1. **Este archivo** (INICIO_AQUÍ.md) — contexto rápido.
2. **PROJECT_STATUS.md** — estado actual detallado, próximos pasos, hitos.
3. **MARTA.md** (si eres Marta/revisando) — reglas de operación, principios de auditoría.
4. **EDISON.md** (si eres Edison/codeando) — stack, checklist pre-entrega, flujo de trabajo.
5. **ROADMAP.md** — hoja de ruta completa (M1-M7, timeline, deliverables).
6. **Especificación del módulo en desarrollo** (ej. `docs/specs/M1_SPEC.md`).

---

## 🎯 Qué Hacer Ahora (Según tu Rol)

### Si eres **Tom** (Product Owner)

1. Lee **PROJECT_STATUS.md** (sección "Trabajo en Progreso").
2. Propone cambios/nuevos activos/ajustes de parámetros.
3. Marta los audita con critical flaw analysis.
4. Si aprobados, entran al backlog.

**Próximo en tu plato:** validar que SOL/USDT es el primer activo correcto. Luego diseñar DOGE/USDT (volátil caótico).

---

### Si eres **Marta** (Arquitecta en Jefe)

1. Lee **PROJECT_STATUS.md** → "Trabajo en Progreso".
2. Espera **Edison con Tarea #2** (suite de tests).
3. Audita línea por línea:
   - ¿Tests cumplen 90% coverage?
   - ¿mypy --strict OK?
   - ¿ruff check + format OK?
   - ¿Casos de error cubiertos?
4. Aprueba o rechaza con justificación técnica.

**Tu checklist de auditoría:** ver sección "Definition of Done" en `docs/specs/M1_SPEC.md`.

---

### Si eres **Edison** (Programador)

1. Lee **EDISON.md** (stack, reglas, checklist).
2. Lee **PROJECT_STATUS.md** → "Trabajo en Progreso → Tarea #2".
3. **Ejecuta Tarea #2:** suite de tests para M1.
   - Tests para cada método de `SymbolFilters`.
   - Tests para cada tipo de excepción.
   - Tests para `SymbolConfig` con validación cruzada.
   - Mock de `/api/v3/exchangeInfo` (fixture JSON).
   - Output: `pytest --cov ≥ 90%` + `mypy --strict` + `ruff check`.
4. Abre PR a `develop` con descripción + output de tests.
5. Espera auditoría de Marta.

**Archivo clave:** `chimuelo_prime/exchange_config/models.py` (ya implementado, necesita tests).

---

## 📊 Estado de Cada Módulo

| Módulo | Descripción | Status | Próximo |
|--------|-------------|--------|---------|
| **M1** | Exchange Filters (Fundacional) | 🔄 20% (tests) | T#2 → T#3 (cliente) |
| **M2** | API Client + Rate Limiter | ⏸️ 0% | Después M1 |
| **M3** | Grid State Manager (SQLite) | ⏸️ 0% | Después M2 |
| **M4** | Order Execution | ⏸️ 0% | Después M3 |
| **M5** | Grid Engine (Core) | ⏸️ 0% | Después M4 |
| **M6** | Backtesting | ⏸️ 0% | Después M5 |
| **M7** | Bot Orchestrator + CLI | ⏸️ 0% | Después M6 |

---

## 🔗 Mapeo de Documentación

```
docs/
├─ INICIO_AQUÍ.md              ← TÚ ESTÁS AQUÍ
├─ PROJECT_STATUS.md           ← Estado actual + próximos pasos
├─ MARTA.md                    ← Configuración de Marta
├─ EDISON.md                   ← Configuración de Edison
├─ ROADMAP.md                  ← Hoja de ruta M1-M7
└─ specs/
   └─ M1_SPEC.md               ← Especificación detallada de M1
   
Código:
chimuelo_prime/
└─ exchange_config/
   ├─ __init__.py
   ├─ exceptions.py            ← Jerarquía de excepciones
   ├─ models.py                ← SymbolFilters + SymbolConfig
   ├─ client.py                ← (TODO: T#3)
   ├─ service.py               ← (TODO: T#3)
   └─ config_loader.py         ← (TODO: T#3)

tests/
└─ exchange_config/
   ├─ test_models.py           ← (TODO: T#2)
   ├─ test_exceptions.py       ← (TODO: T#2)
   ├─ test_config_loader.py    ← (TODO: T#3)
   └─ fixtures/
      └─ exchange_info_solusdt.json  ← Real Binance response (frozen)
```

---

## 💾 Cómo Guardar y Cargar Sesiones

### Para guardar el contexto actual (antes de salir)

```bash
# Todos los archivos ya están en docs/
# Git lo versionea automáticamente
git add docs/ chimuelo_prime/
git commit -m "Session: [fecha] - [resumen de progreso]"
git push origin develop
```

### Para cargar en nueva sesión

```bash
# Clonar o pull del repo
git clone <repo>
cd chimuelo_prime
cat docs/INICIO_AQUÍ.md  # Este archivo
cat docs/PROJECT_STATUS.md  # Actualizado con hitos
```

---

## 🎓 Principios Clave (No Olvidar)

1. **Decimal-Only:** Cero floats en dinero. Binance rechaza con -1013.
2. **Tests Obligatorios:** ≥ 90% coverage. Sin tests = sin merge.
3. **Especificación Primero:** Edison pregunta antes de decidir (no adivina).
4. **Bloqueante:** M(n) no inicia hasta M(n-1) está 100% con Definition of Done.
5. **Auditoría de Marta:** Línea por línea. Aprobación formal antes de merge.

---

## 📞 Preguntas Rápidas

**P: ¿Qué debo hacer ahora mismo?**
A: Depende de tu rol (ver sección "Qué Hacer Ahora").

**P: ¿Dónde está el código?**
A: `chimuelo_prime/` (modelos completados) + `tests/` (tests por hacer).

**P: ¿Qué es "Definition of Done"?**
A: Checklist en `docs/specs/M1_SPEC.md`, sección "Definition of Done". Todos los criterios deben cumplirse antes de merge.

**P: ¿Bloqueado? ¿Qué hago?**
A: Revisa `PROJECT_STATUS.md` → "Bloqueantes Actuales". Si hay, escalada a Marta.

**P: ¿Cambios en spec?**
A: Ambigüedad → pregunta a Marta. Cambio de scope → Marta autoriza o rechaza.

---

## 🚀 Próximo Hito (Hoy/Mañana)

✅ **Edison:** Entrega Tarea #2 (tests M1).
✅ **Marta:** Audita y aprueba o rechaza.
✅ **Edison:** Itera si rechazado, continúa si aprobado.
✅ **Timeline:** M1 completo en 2 días (hoy + mañana).

---

## 📝 Historial de Sesiones

| Fecha | Qué Pasó | Owner |
|-------|----------|-------|
| 17-18 mayo | Parametrización matemática SOL/USDT | Tom + Marta |
| 18 mayo 02:00 | Especificación M1 + Tarea #1 (modelos) | Marta + Edison |
| 18 mayo (AHORA) | Documentación + Setup de agentes | Tom + Marta |
| 18-19 mayo | Tarea #2 (tests) | Edison (blocked on Marta approval) |

---

## 🎯 Tu Siguiente Paso

1. **Identifica tu rol** (Tom/Marta/Edison).
2. **Lee el archivo de tu rol** (MARTA.md / EDISON.md / project status).
3. **Carga el contexto** de `PROJECT_STATUS.md`.
4. **Ejecuta tu tarea** según el "Qué Hacer Ahora".

---

**Versión:** 1.0
**Última actualización:** 18 mayo 2026
**Estado:** Listo para nueva sesión

*Si algo no está claro, leer los archivos de documentación completos. Están diseñados para ser autosuficientes.*
