# 📚 ÍNDICE COMPLETO — Documentación de Chimuelo Prime

## 🎯 Entrada Rápida (Lee Primero)

👉 **Eres nuevo en el proyecto?** Comienza aquí:
1. [`INICIO_AQUÍ.md`](#inicio) — contexto de 2 minutos + qué hacer ahora.
2. [`PROJECT_STATUS.md`](#status) — estado actual detallado.
3. Tu rol (ver abajo).

---

## 📂 Mapeo de Documentos

### <a name="inicio"></a>🚀 INICIO_AQUÍ.md (Lectura: 2-5 min)
**Para:** Cualquiera que abre una nueva sesión.
**Contiene:**
- Resumen ejecutivo de qué es Chimuelo Prime.
- Dónde estamos ahora (18 mayo 2026, Módulo 1 20%).
- Qué hacer según tu rol (Tom/Marta/Edison).
- Mapa rápido de documentación.
- Preguntas frecuentes.

**Cuándo leer:** PRIMERO, siempre.

---

### <a name="status"></a>📊 PROJECT_STATUS.md (Lectura: 10-15 min)
**Para:** Entender el estado actual del proyecto en detalle.
**Contiene:**
- Resumen ejecutivo (matriz de estado).
- Milestones completados (Phase 0, 1a, 1b).
- Trabajo en progreso (Tareas #2, #3, #4 de M1).
- Bloqueantes actuales (ninguno ahora).
- Módulos pendientes y timeline.
- Documentación actual (qué está done, qué no).
- Decisiones clave y justificación.
- Hitos próximos (1-2 semanas).
- Métricas de éxito definidas.
- Supuestos y riesgos.
- Próxima sesión: qué esperar.

**Cuándo leer:** SEGUNDO, siempre. Actualizar después de cada sesión.

---

### <a name="marta"></a>⚙️ MARTA.md (Lectura: 8-10 min)
**Para:** Comprender cómo Marta audita y toma decisiones.
**Contiene:**
- Rol y responsabilidades de Marta.
- 5 Reglas de Operación estrictas (cero complacencia, abogado del diablo, rigor técnico, enfoque didáctico, autoridad).
- Matriz de decisión (qué hace Marta en cada situación).
- Cómo interactúa con Edison y Tom.
- 7 Principios arquitectónicos no-negociables.
- Checklist de aprobación.
- Frases típicas ("eso no resiste escrutinio", "explícame la teoría").
- Estado actual de Marta.
- Cómo usar a Marta en nueva sesión.

**Cuándo leer:**
- Si eres Marta: siempre (es tu system prompt).
- Si eres Edison: antes de cada entrega (para saber qué espera Marta).
- Si eres Tom: cuando propongas cambios (para anticipar reacciones).

---

### <a name="edison"></a>🔧 EDISON.md (Lectura: 10-12 min)
**Para:** Comprender cómo Edison codea y entrega.
**Contiene:**
- Rol y responsabilidades de Edison.
- Flujo Tom → Marta → Edison.
- 10 Reglas innegociables (especificación primero, testing obligatorio, type hints, Decimal-only, logging, naming, config, docs, Git, no extender scope).
- Ciclo de vida de un módulo (diseño, implementación, entrega, auditoría).
- Stack técnico (Pydantic, structlog, pytest, responses, mypy, ruff).
- Checklist pre-entrega (15 items).
- Contra-ejemplos (qué NO hacer).
- Cómo comunicarse efectivamente con Marta.
- Estado actual de Edison.
- Cómo usar a Edison en nueva sesión.

**Cuándo leer:**
- Si eres Edison: siempre (es tu system prompt).
- Si eres Marta: antes de auditar (para saber qué debería haber hecho Edison).
- Si eres Tom: cuando necesites entender por qué Edison toma tiempo (para respetar los procesos).

---

### <a name="roadmap"></a>🗺️ ROADMAP.md (Lectura: 15-20 min)
**Para:** Entender la hoja de ruta completa del proyecto (M1-M7).
**Contiene:**
- Visión general (7 módulos, dependencias).
- Regla de oro: M(n) no inicia hasta M(n-1) completado.
- **Detalle de cada módulo:**
  - M1: Exchange Configuration (✅ En desarrollo)
  - M2: API Client + Rate Limiter
  - M3: Grid State Manager
  - M4: Order Execution
  - M5: Grid Engine (Core)
  - M6: Backtesting Engine
  - M7: Bot Orchestrator + CLI
- Para cada módulo: timeline, dependencias, entregables, features, testing.
- Gantt chart (estimado).
- Criterios de éxito globales.
- Matriz de riesgos y mitigaciones.
- Escalación.

**Cuándo leer:**
- Cuando necesites entender la arquitectura global.
- Cuando planifiques qué hacer después de M1.
- Cuando estimes timeline o recursos.

---

## 📋 Documentación por Rol

### Si eres **TOM** (Product Owner)

**Lectura esencial:**
1. INICIO_AQUÍ.md (2 min)
2. PROJECT_STATUS.md (15 min)
3. ROADMAP.md (20 min)

**Tu workflow:**
- Propones cambios estratégicos (parámetros, nuevo activos).
- Marta los audita.
- Si aprobados, Edison los implementa.

**Próximo en tu plato:** validar SOL/USDT como primer activo, diseñar DOGE/USDT.

---

### Si eres **MARTA** (Arquitecta en Jefe)

**Lectura esencial:**
1. INICIO_AQUÍ.md (2 min)
2. PROJECT_STATUS.md (15 min)
3. MARTA.md (10 min) — ES TU SYSTEM PROMPT
4. Especificación del módulo actual (ej. M1_SPEC.md)

**Tu workflow:**
- Recibes entregables de Edison.
- Auditas línea por línea contra Definition of Done.
- Apruebas o rechazas con justificación técnica.
- Asesoras a Tom en decisiones estratégicas.

**Próximo:** auditar Tarea #2 de Edison (tests de M1).

---

### Si eres **EDISON** (Programador)

**Lectura esencial:**
1. INICIO_AQUÍ.md (2 min)
2. EDISON.md (12 min) — ES TU SYSTEM PROMPT
3. Especificación del módulo actual (ej. M1_SPEC.md)
4. PROJECT_STATUS.md → "Trabajo en Progreso" (5 min)

**Tu workflow:**
1. Lees especificación completa.
2. Si hay ambigüedad, preguntas a Marta.
3. Codeas siguiendo checklist pre-entrega.
4. Tests desde día uno (≥ 90% coverage).
5. Abres PR con output de tests.
6. Esperas auditoría de Marta.

**Próximo:** ejecutar Tarea #2 (suite de tests para M1).

---

## 🔗 Enlaces Útiles Dentro de los Documentos

### INICIO_AQUÍ.md
- [Qué Hacer Ahora](#qué-hacer-ahora) — instrucciones por rol.
- [Estado de Cada Módulo](#estado-de-cada-módulo) — matriz de progreso.
- [Mapeo de Documentación](#mapeo-de-documentación) — estructura de archivos.

### PROJECT_STATUS.md
- [Milestones Completados](#milestones-completados) — qué hicimos.
- [Trabajo en Progreso](#trabajo-en-progreso) — tareas actuales.
- [Módulos Pendientes](#módulos-pendientes) — qué falta.
- [Decisiones Clave](#decisiones-clave) — por qué tomamos cada decisión.

### ROADMAP.md
- [Gantt Chart](#gantt-chart) — visualización de timeline.
- [Criterios de Éxito](#criterios-de-éxito) — qué significa "done".
- [Riesgos y Mitigaciones](#riesgos-y-mitigaciones) — qué puede fallar.

---

## 📚 Archivos Técnicos (Especificaciones)

### M1_SPEC.md (Cuando exista)
Especificación detallada del Módulo 1:
- 11 secciones (propósito, responsabilidades, estructura, modelos, excepciones, logging, config, testing, control de versiones, Definition of Done, qué NO aceptar).
- Modelo de dominio (SymbolFilters, SymbolConfig).
- Policy de testing (pytest + responses).
- Checklist de auditoría.

**Ubicación:** `docs/specs/M1_SPEC.md` (ya existe, cópialo aquí después).

---

## 💾 Cómo Navegar Este Proyecto

### Primera vez (nueva sesión)

```
1. cd chimuelo_prime
2. cat docs/INICIO_AQUÍ.md           # 2 min, contexto rápido
3. cat docs/PROJECT_STATUS.md        # 15 min, estado detallado
4. Según tu rol, lee tu archivo:
   - Tom → nada adicional (o ROADMAP si interesa)
   - Marta → MARTA.md + especificación actual
   - Edison → EDISON.md + especificación actual
5. Ejecuta tu tarea según "Qué Hacer Ahora"
```

### Al finalizar sesión

```
1. Actualiza PROJECT_STATUS.md con tus hitos.
2. Git add/commit/push docs/
3. Deja una nota en INICIO_AQUÍ.md de cuándo fue tu sesión y qué completaste.
```

---

## 🎯 Orden Recomendado de Lectura (Cualquier Rol)

**Rápido (5 min):**
1. INICIO_AQUÍ.md

**Completo (45 min):**
1. INICIO_AQUÍ.md (2 min)
2. PROJECT_STATUS.md (15 min)
3. Tu archivo de rol (10-12 min)
4. ROADMAP.md (20 min)

**Exhaustivo (1-1.5 horas):**
Completo + Especificación del módulo actual (30 min) + leer código base (15-30 min).

---

## ❓ Preguntas Frecuentes

**P: ¿Dónde está la especificación de M1?**
A: Fue entregada como texto el 18 mayo. Debe existir como `docs/specs/M1_SPEC.md`. Si no existe, reconstruye desde PROJECT_STATUS.md.

**P: ¿Dónde está el código?**
A: `chimuelo_prime/exchange_config/` contiene models.py y exceptions.py. Tests aún por hacer (Edison).

**P: ¿Qué significa "Definition of Done"?**
A: Checklist en ROADMAP.md o M1_SPEC.md. Todos los criterios deben cumplirse antes de merge.

**P: ¿Cómo sé si estoy bloqueado?**
A: Ver PROJECT_STATUS.md → "Bloqueantes Actuales". Si hay, escala a Marta.

**P: ¿Ambigüedad en especificación?**
A: Pregunta a Marta ANTES de decidir. No adivines.

---

## 📞 Contacto / Escalación

Si algo no está claro:
1. Busca en PROJECT_STATUS.md.
2. Busca en ROADMAP.md.
3. Busca en tu archivo de rol (MARTA/EDISON).
4. Si aún no está claro, abre issue en el repo o pide aclaración a Marta.

---

## 🔐 Principios Clave (Nunca Olvides)

1. **Decimal-Only:** Cero floats en dinero.
2. **Tests Obligatorios:** ≥ 90% coverage.
3. **Especificación Primero:** Pregunta antes de decidir.
4. **Bloqueante:** M(n) no inicia hasta M(n-1) completado.
5. **Auditoría de Marta:** Línea por línea, aprobación formal.

---

**Versión:** 1.0
**Última actualización:** 18 mayo 2026 02:50 UTC
**Mantenedor:** Tom (PM), Marta (Arquitecta), Edison (Programador)

---

## 📊 Resumen Visual (Cargar primero)

```
TÚ (nueva sesión)
  ↓
  INICIO_AQUÍ.md (2 min)
  ↓
  PROJECT_STATUS.md (15 min)
  ↓
  ¿Cuál es tu rol?
  ├─ Tom? → ROADMAP.md (opcional)
  ├─ Marta? → MARTA.md + especificación
  └─ Edison? → EDISON.md + especificación
  ↓
  Ejecuta tu tarea
```

---

*Este documento es la brújula del proyecto. Úsalo para navegar.*
