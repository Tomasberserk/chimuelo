# Pesos de endpoints Binance Spot (request weight, 2024).
# Single Source of Truth para todos los módulos de Chimuelo Prime.
# Importar desde aquí; nunca redefinir localmente en cada módulo.
WEIGHT_PLACE_ORDER = 1    # POST /api/v3/order
WEIGHT_CANCEL_ORDER = 1   # DELETE /api/v3/order
WEIGHT_QUERY_ORDER = 2    # GET /api/v3/order
WEIGHT_OPEN_ORDERS = 3    # GET /api/v3/openOrders (con symbol)
