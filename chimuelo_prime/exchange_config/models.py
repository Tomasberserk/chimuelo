"""Modelos de dominio del módulo exchange_config.

Define dos modelos Pydantic inmutables:

* `SymbolFilters`: snapshot de los filtros operativos que Binance impone
  sobre un símbolo (tick_size, step_size, min_notional, etc.). Es la
  fuente única de verdad para validar precios y cantidades antes de
  enviar órdenes.

* `SymbolConfig`: contrato de configuración por símbolo que el futuro
  GridEngine (Módulo 5) recibirá por inyección de dependencias. Cumple
  con el principio Open/Closed (SOLID-O): el motor no conoce símbolos
  específicos, depende de esta abstracción.

REGLA INNEGOCIABLE: cero `float` en cálculos financieros. Solo `Decimal`.
Los floats causan errores de precisión que Binance rechaza con código
-1013 (filter failure). Pydantic v2 hace coerción automática desde str
o int, pero NO desde float (lo bloqueamos a nivel de schema).
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from chimuelo_prime.exchange_config.exceptions import FilterValidationError


# --------------------------------------------------------------------------- #
# SymbolFilters
# --------------------------------------------------------------------------- #
class SymbolFilters(BaseModel):
    """Snapshot inmutable de los filtros que Binance impone sobre un símbolo.

    Los nombres de los campos corresponden a las claves en la respuesta de
    `/api/v3/exchangeInfo`, traducidas a snake_case según convención Python.

    Mapeo desde Binance:
        PRICE_FILTER.tickSize  -> tick_size
        PRICE_FILTER.minPrice  -> min_price
        PRICE_FILTER.maxPrice  -> max_price
        LOT_SIZE.stepSize      -> step_size
        LOT_SIZE.minQty        -> min_qty
        LOT_SIZE.maxQty        -> max_qty
        NOTIONAL.minNotional   -> min_notional
        PERCENT_PRICE_BY_SIDE.bidMultiplierUp    -> pct_up
        PERCENT_PRICE_BY_SIDE.bidMultiplierDown  -> pct_down

    El modelo es `frozen=True`: una vez creado, no puede mutarse. Si los
    filtros del exchange cambian en runtime, el servicio debe construir
    una instancia NUEVA, no mutar la existente. Esto garantiza thread-safety
    y previene bugs sutiles donde un módulo lee filtros mientras otro los
    modifica.
    """

    model_config = ConfigDict(
        frozen=True,
        strict=True,  # No coerción implícita; tipos explícitos
        arbitrary_types_allowed=False,
    )

    symbol: str = Field(..., min_length=1, description="Par de trading, ej. 'SOLUSDT'")

    # PRICE_FILTER
    tick_size: Decimal = Field(..., gt=0, description="Incremento mínimo de precio")
    min_price: Decimal = Field(..., ge=0, description="Precio mínimo aceptado")
    max_price: Decimal = Field(..., gt=0, description="Precio máximo aceptado")

    # LOT_SIZE
    step_size: Decimal = Field(..., gt=0, description="Incremento mínimo de cantidad")
    min_qty: Decimal = Field(..., ge=0, description="Cantidad mínima aceptada")
    max_qty: Decimal = Field(..., gt=0, description="Cantidad máxima aceptada")

    # NOTIONAL
    min_notional: Decimal = Field(
        ..., gt=0, description="Valor mínimo notional (precio * cantidad)"
    )

    # PERCENT_PRICE_BY_SIDE
    pct_up: Decimal = Field(
        ..., gt=0, description="Multiplicador máximo del precio respecto al promedio"
    )
    pct_down: Decimal = Field(
        ..., gt=0, description="Multiplicador mínimo del precio respecto al promedio"
    )

    # --------------------------------------------------------------------- #
    # Validators
    # --------------------------------------------------------------------- #
    @field_validator(
        "tick_size",
        "min_price",
        "max_price",
        "step_size",
        "min_qty",
        "max_qty",
        "min_notional",
        "pct_up",
        "pct_down",
        mode="before",
    )
    @classmethod
    def _reject_floats(cls, v: object) -> object:
        """Bloquea floats explícitamente.

        Pydantic v2 con strict=True ya rechaza int->Decimal sin str intermedia,
        pero floats pueden colarse vía coerción de NumPy/Pandas. Bloqueo
        defensivo: si llega un float, fallar ruidosamente.
        """
        if isinstance(v, float):
            raise TypeError(
                f"float prohibido en filtros financieros (valor recibido: {v!r}). "
                "Convierte a str o Decimal antes de instanciar SymbolFilters."
            )
        return v

    # --------------------------------------------------------------------- #
    # API pública: validación
    # --------------------------------------------------------------------- #
    def validate_price(self, price: Decimal) -> None:
        """Valida que un precio cumpla PRICE_FILTER.

        Levanta `FilterValidationError` si:
            * price < min_price
            * price > max_price
            * price no es múltiplo exacto de tick_size

        El chequeo de múltiplo usa el módulo de Decimal, no comparación de
        floats. La aritmética de Decimal es exacta en base 10.
        """
        if price < self.min_price:
            raise FilterValidationError(
                f"price={price} < min_price={self.min_price} ({self.symbol})"
            )
        if price > self.max_price:
            raise FilterValidationError(
                f"price={price} > max_price={self.max_price} ({self.symbol})"
            )
        # Múltiplo exacto: (price - min_price) % tick_size == 0
        # Se resta min_price porque el rango válido es min_price + n*tick_size.
        remainder = (price - self.min_price) % self.tick_size
        if remainder != Decimal("0"):
            raise FilterValidationError(
                f"price={price} no es múltiplo de tick_size={self.tick_size} "
                f"({self.symbol}); offset desde min_price: {remainder}"
            )

    def validate_quantity(self, qty: Decimal) -> None:
        """Valida que una cantidad cumpla LOT_SIZE.

        Levanta `FilterValidationError` si:
            * qty < min_qty
            * qty > max_qty
            * qty no es múltiplo exacto de step_size
        """
        if qty < self.min_qty:
            raise FilterValidationError(f"qty={qty} < min_qty={self.min_qty} ({self.symbol})")
        if qty > self.max_qty:
            raise FilterValidationError(f"qty={qty} > max_qty={self.max_qty} ({self.symbol})")
        remainder = (qty - self.min_qty) % self.step_size
        if remainder != Decimal("0"):
            raise FilterValidationError(
                f"qty={qty} no es múltiplo de step_size={self.step_size} "
                f"({self.symbol}); offset desde min_qty: {remainder}"
            )

    def validate_notional(self, price: Decimal, qty: Decimal) -> None:
        """Valida que (price * qty) cumpla NOTIONAL.

        El notional es el valor total de la orden en quote currency (USDT
        en nuestro caso). Binance rechaza órdenes con notional < min_notional
        con código -1013 LOT_SIZE / MIN_NOTIONAL.
        """
        notional = price * qty
        if notional < self.min_notional:
            raise FilterValidationError(
                f"notional={notional} (price={price} * qty={qty}) < "
                f"min_notional={self.min_notional} ({self.symbol})"
            )

    # --------------------------------------------------------------------- #
    # API pública: redondeo hacia abajo
    # --------------------------------------------------------------------- #
    def round_price_to_tick(self, price: Decimal) -> Decimal:
        """Redondea un precio al múltiplo de tick_size más cercano hacia ABAJO.

        ROUND_DOWN es la decisión correcta para grid trading:
            * En órdenes de compra: garantiza no superar el precio máximo
              planeado, preservando el margen de spacing calculado.
            * En órdenes de venta: redondear hacia abajo reduce
              marginalmente la ganancia esperada, pero garantiza
              ejecutabilidad. ROUND_UP arriesgaría superar max_price.

        Fórmula: floor((price - min_price) / tick_size) * tick_size + min_price.
        """
        steps = ((price - self.min_price) / self.tick_size).quantize(
            Decimal("1"), rounding=ROUND_DOWN
        )
        return steps * self.tick_size + self.min_price

    def round_qty_to_step(self, qty: Decimal) -> Decimal:
        """Redondea una cantidad al múltiplo de step_size más cercano hacia ABAJO.

        ROUND_DOWN es crítico aquí: redondear cantidad hacia arriba puede
        provocar que el capital asignado al nivel sea insuficiente para
        cubrir la orden, generando rechazo por insufficient balance.
        """
        steps = ((qty - self.min_qty) / self.step_size).quantize(Decimal("1"), rounding=ROUND_DOWN)
        return steps * self.step_size + self.min_qty


# --------------------------------------------------------------------------- #
# SymbolConfig
# --------------------------------------------------------------------------- #
class SymbolConfig(BaseModel):
    """Contrato de configuración por símbolo para el GridEngine (Módulo 5).

    Este modelo materializa el principio Open/Closed (SOLID-O):
        * El `GridEngine` NO conoce símbolos específicos.
        * Recibe un `SymbolConfig` por inyección de dependencias.
        * Para soportar un nuevo activo (DOGE/USDT, PEPE/USDT), basta con
          instanciar otro `SymbolConfig`. No se modifica el motor.

    Combina los filtros del exchange (vienen de Binance) con los parámetros
    de estrategia (vienen del usuario / cálculo cuantitativo).
    """

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        arbitrary_types_allowed=False,
    )

    # Filtros del exchange (autoridad: Binance)
    filters: SymbolFilters

    # Parámetros de estrategia (autoridad: usuario / cálculo offline)
    upper_bound: Decimal = Field(..., gt=0, description="Límite superior del grid")
    lower_bound: Decimal = Field(..., gt=0, description="Límite inferior del grid")
    grid_levels: int = Field(..., gt=1, description="Número de niveles del grid")
    capital_per_order: Decimal = Field(
        ..., gt=0, description="Capital asignado por orden en quote currency"
    )
    capital_weight: Decimal = Field(
        default=Decimal("1.0"),
        gt=0,
        le=1,
        description=(
            "Peso del capital total asignado a este símbolo en estrategia "
            "multi-activo (risk parity: 1/sigma_i normalizado). Default 1.0 "
            "para configuración mono-activo."
        ),
    )

    @field_validator(
        "upper_bound",
        "lower_bound",
        "capital_per_order",
        "capital_weight",
        mode="before",
    )
    @classmethod
    def _reject_floats(cls, v: object) -> object:
        if isinstance(v, float):
            raise TypeError(
                f"float prohibido en parámetros financieros (valor: {v!r}). "
                "Convierte a str o Decimal."
            )
        return v

    def model_post_init(self, __context: object) -> None:
        """Validaciones cruzadas entre campos (post-construcción).

        Pydantic v2 ejecuta `model_post_init` después de validar todos los
        campos individuales, momento ideal para validar relaciones entre
        ellos.
        """
        if self.lower_bound >= self.upper_bound:
            raise ValueError(
                f"lower_bound={self.lower_bound} debe ser < upper_bound={self.upper_bound}"
            )
        # El símbolo del filtro debe coincidir con la intención del config.
        # No tenemos un campo `symbol` separado a propósito: el símbolo vive
        # en `filters.symbol` como única fuente de verdad.
        if self.filters.symbol == "":  # pragma: no cover
            raise ValueError("filters.symbol no puede estar vacío")
