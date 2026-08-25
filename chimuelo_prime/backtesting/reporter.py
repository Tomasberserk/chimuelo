"""Generador de informes premium para el módulo de Backtesting (M6).

Permite imprimir resúmenes formateados en consola con estética profesional
y exportar los resultados y métricas del backtest a archivos JSON locales.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from chimuelo_prime.backtesting.engine import BacktestReport
from chimuelo_prime.exchange_config.logger import get_logger


class DecimalEncoder(json.JSONEncoder):
    """Codificador JSON personalizado para manejar objetos Decimal y datetime."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return str(obj)
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return super().default(obj)


class BacktestReporter:
    """Generador de reportes en consola y exportación en disco para backtesting de Grid."""

    def __init__(self, report: BacktestReport) -> None:
        """Inicializa el reporter con un reporte generado por el simulador de grid.

        Args:
            report: Reporte de backtesting unificado.
        """
        self._report = report
        self._log = get_logger(__name__)

    def print_terminal_report(self) -> None:
        """Muestra en la consola un reporte detallado y estilizado del backtest."""
        mode_str = (
            "CONTINUO (Classic)" if self._report.recreate_buy_on_sell_fill else "ESTRICTO (M5)"
        )

        print("\n" + "=" * 80)
        print(" CHIMUELO PRIME GRID TRADING BOT — INFORME DE BACKTESTING ".center(80, "="))
        print("=" * 80)

        # Información general del Backtest
        print("\n[+] CONFIGURACIÓN GENERAL:")
        print(f"  • Activo / Símbolo:       {self._report.symbol}")
        print(f"  • Intervalo de Velas:     {self._report.interval}")
        print(
            f"  • Periodo Simulado:       {self._report.start_time}  -->  {self._report.end_time}"
        )
        print(f"  • Modo de Operación:      {mode_str}")

        # Métricas de Balance
        print("\n[+] RENDIMIENTO DE PORTAFOLIO:")
        print(f"  • Capital Inicial:        {self._report.initial_cash:>15} USDT")
        print(f"  • Efectivo Final:         {self._report.final_cash:>15} USDT")
        print(f"  • Patrimonio Neto Final:  {self._report.final_equity:>15} USDT")
        print(f"  • Retorno Total (PnL %):  {self._report.total_return_pct:>14.4f} %")
        print(f"  • Máximo Drawdown:        {self._report.max_drawdown_pct:>14.4f} %")

        # Ratios de Calidad Financiera
        print("\n[+] RATIOS Y EVALUACIÓN DE RIESGO:")
        print(f"  • Profit Factor:          {str(self._report.profit_factor):>15}")
        print(f"  • Ratio de Sortino (An.): {str(self._report.sortino_ratio):>15}")
        print(f"  • Ratio de Calmar (An.):  {str(self._report.calmar_ratio):>15}")

        # Estadísticas de Operaciones
        print("\n[+] ESTADÍSTICAS OPERATIVAS:")
        print(f"  • Total de Niveles / Órdenes: {self._report.total_trades:>11}")
        print(f"  • Operaciones Completadas:    {self._report.completed_trades:>11}")
        print(f"  • Tasa de Acierto (Win Rate): {self._report.win_rate_pct:>10.2f} %")

        # Lista de Trades completados (resumen)
        if self._report.trades:
            print("\n[+] DETALLE DE ÚLTIMAS OPERACIONES (Muestra):")
            print(
                f"  {'Nivel':<6} | {'Precio Compra':<14} | {'Precio Venta':<14} | {'Cantidad':<12} | {'PnL (USDT)':<12} | {'Fecha/Hora Venta'}"
            )
            print("  " + "-" * 90)
            # Mostrar los últimos 5 trades como resumen
            sample_trades = self._report.trades[-5:]
            for t in sample_trades:
                print(
                    f"  {t.level_index:<6} | {t.buy_price:>14.4f} | {t.sell_price:>14.4f} | {t.qty:>12.4f} | {t.pnl:>12.4f} | {t.sell_time}"
                )
            if len(self._report.trades) > 5:
                print(f"  ... y {len(self._report.trades) - 5} operaciones adicionales.")
        else:
            print("\n[!] No se completaron operaciones de venta en este ciclo.")

        print("\n" + "=" * 80)
        print(" FIN DEL REPORTE CHIMUELO PRIME ".center(80, "="))
        print("=" * 80 + "\n")

    def export_json(self, file_path: str | Path) -> None:
        """Exporta los resultados a un archivo JSON legible.

        Args:
            file_path: Ruta del archivo JSON a guardar.
        """
        path = Path(file_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            report_dict = self._report.model_dump()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(report_dict, f, cls=DecimalEncoder, indent=2, ensure_ascii=False)
            self._log.info("backtest.export_success", file=str(path))
        except Exception as exc:
            self._log.error("backtest.export_failed", file=str(path), error=str(exc))
            raise


class SignalBacktestReporter:
    """Generador de reportes en consola y exportación para estrategias cuantitativas direccionales."""

    def __init__(self, report: Any) -> None:
        """Inicializa el reporter con un SignalBacktestReport.

        Args:
            report: Reporte cuantitativo de estrategia de señales.
        """
        self._report = report
        self._log = get_logger(__name__)

    def print_terminal_report(self) -> None:
        """Muestra en la consola un informe detallado y estilizado de la estrategia cuantitativa."""
        rep = self._report
        print("\n" + "=" * 82)
        print(f" CHIMUELO PRIME QUANT STRATEGY BACKTEST — {rep.strategy_name} ".center(82, "="))
        print("=" * 82)

        # Configuración General
        print("\n[+] PARÁMETROS DE LA SIMULACIÓN:")
        print(f"  • Estrategia:             {rep.strategy_name}")
        print(f"  • Activo / Símbolo:       {rep.symbol}")
        print(f"  • Temporalidad (Candles): {rep.interval}")
        print(f"  • Rango Temporal:         {rep.start_time}  -->  {rep.end_time}")

        # Rendimiento de Portafolio
        print("\n[+] RENDIMIENTO DE PORTAFOLIO:")
        print(f"  • Capital Inicial:        ${rep.initial_cash:>12.2f} USDT")
        print(f"  • Efectivo Final:         ${rep.final_cash:>12.2f} USDT")
        print(f"  • Patrimonio Neto Final:  ${rep.final_equity:>12.2f} USDT")
        print(f"  • Beneficio Neto (USD):   ${rep.net_profit_usd:>+12.4f} USDT")
        print(f"  • Retorno Total:          {rep.total_return_pct:>+13.2f} %")
        print(f"  • Máximo Drawdown:        {rep.max_drawdown_pct:>13.2f} %")

        # Ratios y Calidad Cuantitativa
        print("\n[+] MÉTRICAS Y RATIOS CUANTITATIVOS:")
        print(f"  • Profit Factor:          {str(rep.profit_factor):>14}")
        print(f"  • Ratio de Sortino (An.): {str(rep.sortino_ratio):>14}")
        print(f"  • Ratio de Calmar (An.):  {str(rep.calmar_ratio):>14}")

        # Estadísticas de Operaciones
        print("\n[+] ESTADÍSTICAS OPERATIVAS:")
        print(f"  • Total de Operaciones:   {rep.total_trades:>14}")
        print(f"  • Trades Ganadores:       {rep.winning_trades:>14}")
        print(f"  • Trades Perdedores:      {rep.losing_trades:>14}")
        print(f"  • Win Rate:               {rep.win_rate_pct:>13.2f} %")
        print(f"  • PnL Promedio por Trade: ${rep.average_trade_pnl:>+12.4f} USDT")
        print(f"  • Ganancia Promedio (Win):${rep.average_win_pnl:>+12.4f} USDT")
        print(f"  • Pérdida Promedio (Loss):${rep.average_loss_pnl:>+12.4f} USDT")
        print(f"  • Total Comisiones (Fees):${rep.total_fees_paid:>12.4f} USDT")

        # Muestra de operaciones
        if rep.trades:
            print("\n[+] DETALLE DE OPERACIONES EJECUTADAS (Últimas):")
            print(
                f"  {'ID':<4} | {'Entrada (USDT)':<14} | {'Salida (USDT)':<14} | {'Cant.':<10} | {'PnL Neto (USDT)':<16} | {'PnL %':<10} | {'Motivo Cierre'}"
            )
            print("  " + "-" * 92)
            sample_trades = rep.trades[-10:]
            for t in sample_trades:
                print(
                    f"  {t.trade_id:<4} | {t.entry_price:>14.4f} | {t.exit_price:>14.4f} | {t.qty:>10.4f} | {t.net_pnl:>+16.4f} | {t.net_pnl_pct:>+9.2f}% | {t.exit_reason}"
                )
            if len(rep.trades) > 10:
                print(f"  ... y {len(rep.trades) - 10} operaciones adicionales.")
        else:
            print("\n[!] No se generaron operaciones en el periodo analizado.")

        print("\n" + "=" * 82)
        print(" FIN DEL REPORTE CUANTITATIVO CHIMUELO PRIME ".center(82, "="))
        print("=" * 82 + "\n")

    def export_json(self, file_path: str | Path) -> None:
        """Exporta los resultados a un archivo JSON legible.

        Args:
            file_path: Ruta del archivo JSON a guardar.
        """
        path = Path(file_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            report_dict = self._report.model_dump()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(report_dict, f, cls=DecimalEncoder, indent=2, ensure_ascii=False)
            self._log.info("backtest.export_success", file=str(path))
        except Exception as exc:
            self._log.error("backtest.export_failed", file=str(path), error=str(exc))
            raise
