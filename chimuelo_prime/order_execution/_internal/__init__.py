# Paquete interno de order_execution/.
#
# Restricción de producción: ningún módulo fuera de order_execution/ debe importar
# desde _internal/. M5, M7 y cualquier otro módulo downstream consumen únicamente
# la API pública expuesta en order_execution/__init__.py.
#
# Tests: los tests unitarios de _internal/ (ej. test_payload_builder.py) pueden
# importar directamente desde aquí para testear funciones puras en aislamiento.
# Eso es correcto — la restricción aplica a código de producción, no a tests.
