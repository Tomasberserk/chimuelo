# Chimuelo Prime — Módulo 1: Exchange Configuration & Filter Validation

Single Source of Truth para los filtros operativos de Binance.
Cualquier módulo que necesite validar precios, cantidades o notional
depende de este módulo.

---

## Estructura

```
chimuelo_prime/exchange_config/
├── exceptions.py      # Jerarquía de excepciones tipificadas
├── models.py          # SymbolFilters, SymbolConfig (Pydantic, frozen, Decimal-only)
├── client.py          # BinancePublicClient — wrapper HTTP sin autenticación
├── service.py         # ExchangeConfigService — fachada pública
├── config_loader.py   # load_config() — carga y valida chimuelo.yaml
└── logger.py          # get_logger(), configure_logging()

config/
└── chimuelo.yaml      # Configuración externalizada (entornos, símbolos, logging)

tests/exchange_config/
├── fixtures/
│   └── exchange_info_solusdt.json   # Respuesta real de /api/v3/exchangeInfo
├── test_client.py
├── test_config_loader.py
├── test_exceptions.py
├── test_models.py
└── test_service.py
```

---

## Instalación

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

---

## Uso rápido

### 1. Cargar configuración

```python
from pathlib import Path
from chimuelo_prime.exchange_config import load_config, configure_logging

config = load_config(Path("config/chimuelo.yaml"))
configure_logging(level=config.logging.level, fmt=config.logging.format)

env = config.active_env
print(env.base_url)          # https://testnet.binance.vision
print(config.symbols)        # ['SOLUSDT']
```

### 2. Obtener filtros desde Binance

```python
from chimuelo_prime.exchange_config import BinancePublicClient, ExchangeConfigService

client = BinancePublicClient(
    base_url=config.active_env.base_url,
    timeout=config.active_env.http_timeout_seconds,
)
service = ExchangeConfigService(client)

filters = service.fetch_symbol_filters("SOLUSDT")
print(filters.tick_size)      # Decimal('0.01000000')
print(filters.min_notional)   # Decimal('5.00000000')
client.close()
```

### 3. Validar precio y cantidad antes de una orden

```python
from decimal import Decimal
from chimuelo_prime.exchange_config import FilterValidationError

price = Decimal("172.50")
qty   = Decimal("0.10")

try:
    filters.validate_price(price)
    filters.validate_quantity(qty)
    filters.validate_notional(price, qty)
    print("Orden válida")
except FilterValidationError as e:
    print(f"Orden rechazada: {e}")
```

### 4. Redondear al tick/step más cercano (ROUND_DOWN)

```python
raw_price = Decimal("172.537")
safe_price = filters.round_price_to_tick(raw_price)
# Decimal('172.53')  — nunca se redondea hacia arriba

raw_qty = Decimal("0.1234")
safe_qty = filters.round_qty_to_step(raw_qty)
# Decimal('0.1200')
```

---

## Excepciones

| Excepción | Cuándo se lanza |
|-----------|----------------|
| `ExchangeUnreachableError` | Timeout, error de red, HTTP ≥ 400 |
| `InvalidSymbolError` | El símbolo no existe en Binance |
| `FilterParsingError` | Estructura inesperada en la respuesta |
| `FilterValidationError` | Precio/cantidad/notional viola un filtro |
| `ConfigFileNotFoundError` | El YAML no existe en la ruta indicada |
| `ConfigValidationError` | El YAML está malformado o incompleto |

Todas heredan de `ChimueloException` — se pueden capturar con un solo `except`.

---

## Demo

```bash
python demo_m1.py
```

Carga `config/chimuelo.yaml`, parsea el fixture local de SOLUSDT y muestra
los filtros operativos con ejemplos de validación y redondeo.

---

## Tests

```bash
# Suite completa
pytest

# Con cobertura
pytest --cov=chimuelo_prime --cov-report=term-missing

# Calidad de código
mypy chimuelo_prime --strict
ruff check chimuelo_prime tests
ruff format chimuelo_prime tests
```

**Resultado actual:** 129 tests, 99% coverage, mypy --strict OK, ruff OK.

---

## Reglas de diseño

- **Cero floats.** Todos los valores financieros usan `Decimal`. Los modelos
  rechazan floats explícitamente en los validators.
- **Modelos inmutables.** `SymbolFilters` y `SymbolConfig` son `frozen=True`.
  Si los filtros cambian, se construye una instancia nueva.
- **Inyección de dependencias.** `BinancePublicClient` se inyecta en
  `ExchangeConfigService`. Facilita el testing y cumple DIP (SOLID-D).
- **ROUND_DOWN siempre.** Redondear hacia arriba en órdenes de compra puede
  superar el capital asignado o el `max_price`. ROUND_DOWN es safe por defecto.
- **Falla ruidosamente.** Si `chimuelo.yaml` no existe o es inválido, el proceso
  no arranca. Nunca silencioso.
