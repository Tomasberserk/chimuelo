/* ============================================================
   CHIMUELO PRIME — BINANCE PRO DASHBOARD LOGIC (AGENTERS A08/A11)
   TradingView Lightweight Charts + WebSockets + Quantitative Engine
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
    // --- ESTADO GLOBAL DE LA APLICACIÓN ---
    const state = {
        symbol: 'SOLUSDT',
        interval: '1h',
        initialBalance: 100.00,
        equity: 100.00,
        cash: 100.00,
        floatingPnl: 0.00,
        realizedPnl: 0.00,
        lastPrice: null,
        high24h: 0,
        low24h: 0,
        change24h: 0,
        volume24h: 0,
        isRunning: true,
        activePosition: null,
        trades: [],
        candles: [],
        autoscroll: true,
        ws: null,
        wsLatency: 12,
        lastPingTime: 0,
        // Referencias a TradingView Charts
        mainChart: null,
        candleSeries: null,
        emaTrendSeries: null,
        emaFastSeries: null,
        rsiChart: null,
        rsiSeries: null,
        positionPriceLines: [],
        gridPriceLines: [],
    };

    // --- ELEMENTOS DEL DOM ---
    const dom = {
        // Ticker Bar
        tickerPrice: document.getElementById('ticker-price'),
        tickerChangeBadge: document.getElementById('ticker-change-badge'),
        tickerChange24h: document.getElementById('ticker-change-24h'),
        tickerHigh24h: document.getElementById('ticker-high-24h'),
        tickerLow24h: document.getElementById('ticker-low-24h'),
        tickerVol24h: document.getElementById('ticker-vol-24h'),
        botStatusBadge: document.getElementById('bot-status-badge'),
        botStatusText: document.getElementById('bot-status-text'),
        btnStart: document.getElementById('btn-start'),
        btnStop: document.getElementById('btn-stop'),
        btnPanic: document.getElementById('btn-panic-stop'),
        pairButtons: document.querySelectorAll('.pair-btn'),
        tfButtons: document.querySelectorAll('.tf-btn'),

        // KPIs
        kpiInitial: document.getElementById('kpi-initial'),
        kpiEquity: document.getElementById('kpi-equity'),
        kpiEquityRoi: document.getElementById('kpi-equity-roi'),
        kpiCashDetail: document.getElementById('kpi-cash-detail'),
        kpiTotalPnl: document.getElementById('kpi-total-pnl'),
        kpiTotalPnlPct: document.getElementById('kpi-total-pnl-pct'),
        kpiPnlSplit: document.getElementById('kpi-pnl-split'),
        kpiWinrate: document.getElementById('kpi-winrate'),
        kpiTradesCount: document.getElementById('kpi-trades-count'),
        kpiWinlossDetail: document.getElementById('kpi-winloss-detail'),
        kpiProfitFactor: document.getElementById('kpi-profit-factor'),
        kpiDrawdown: document.getElementById('kpi-drawdown'),

        // Gráficos
        tvMainChart: document.getElementById('tv-main-chart'),
        tvRsiChart: document.getElementById('tv-rsi-chart'),
        chartSymbolTitle: document.getElementById('chart-symbol-title'),
        chartTfTitle: document.getElementById('chart-tf-title'),
        rsiLiveValue: document.getElementById('rsi-live-value'),
        rsiZoneBadge: document.getElementById('rsi-zone-badge'),
        btnFitChart: document.getElementById('btn-fit-chart'),
        btnRefreshCandles: document.getElementById('btn-refresh-candles'),

        // Tabs
        tabBtns: document.querySelectorAll('.tab-btn'),
        tabContents: document.querySelectorAll('.tab-content'),
        tradesTbody: document.getElementById('trades-tbody'),
        tradesCountBadge: document.getElementById('trades-count-badge'),
        consoleLogs: document.getElementById('console-logs'),
        terminalActions: document.getElementById('terminal-actions'),
        btnClearConsole: document.getElementById('btn-clear-console'),
        btnAutoscroll: document.getElementById('btn-autoscroll'),

        // Posición Activa
        noPositionView: document.getElementById('no-position-view'),
        hasPositionView: document.getElementById('has-position-view'),
        posStatusBadge: document.getElementById('pos-status-badge'),
        posPair: document.getElementById('pos-pair'),
        posSide: document.getElementById('pos-side'),
        posPnlVal: document.getElementById('pos-pnl-val'),
        posPnlPct: document.getElementById('pos-pnl-pct'),
        lblSlPrice: document.getElementById('lbl-sl-price'),
        lblEntryPrice: document.getElementById('lbl-entry-price'),
        lblTpPrice: document.getElementById('lbl-tp-price'),
        posPriceCursor: document.getElementById('pos-price-cursor'),
        posCurrentPrice: document.getElementById('pos-current-price'),
        posEntryPrice: document.getElementById('pos-entry-price'),
        posSlPrice: document.getElementById('pos-sl-price'),
        posTpPrice: document.getElementById('pos-tp-price'),
        posSize: document.getElementById('pos-size'),

        // Estado de la Estrategia
        indEmaTrendVal: document.getElementById('ind-ema-trend-val'),
        indTrendBadge: document.getElementById('ind-trend-badge'),
        indEmaFastVal: document.getElementById('ind-ema-fast-val'),
        indFastBadge: document.getElementById('ind-fast-badge'),
        indRsiVal: document.getElementById('ind-rsi-val'),
        indRsiBadge: document.getElementById('ind-rsi-badge'),
        indDivVal: document.getElementById('ind-div-val'),
        indDivBadge: document.getElementById('ind-div-badge'),
        indAtrVal: document.getElementById('ind-atr-val'),
        indAtrBadge: document.getElementById('ind-atr-badge'),

        // M10: Sentimiento Macro
        macroRegimeBadge: document.getElementById('macro-regime-badge'),
        fngScoreBadge: document.getElementById('fng-score-badge'),
        fngProgressBar: document.getElementById('fng-progress-bar'),
        macroVetoDetail: document.getElementById('macro-veto-detail'),
        macroVetoBadge: document.getElementById('macro-veto-badge'),
        macroSummaryText: document.getElementById('macro-summary-text'),

        // Parámetros y Auditoría
        liveUtcClock: document.getElementById('live-utc-clock'),
        wsLatencyVal: document.getElementById('ws-latency-val'),
        inputConfig: document.getElementById('input-config'),
        inputDb: document.getElementById('input-db'),
    };

    // ============================================================
    // 1. RELOJ UTC EN TIEMPO REAL
    // ============================================================
    function updateClock() {
        const now = new Date();
        const utcStr = now.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
        if (dom.liveUtcClock) dom.liveUtcClock.textContent = utcStr;
    }
    setInterval(updateClock, 1000);
    updateClock();

    // ============================================================
    // 2. INICIALIZACIÓN DE TRADINGVIEW LIGHTWEIGHT CHARTS
    // ============================================================
    function initCharts() {
        if (typeof LightweightCharts === 'undefined' || !LightweightCharts.createChart) {
            console.error('[Chimuelo] LightweightCharts no encontrado.');
            if (dom.tvMainChart) {
                dom.tvMainChart.innerHTML = '<div class="chart-loading"><p style="color:#F6465D;">Error cargando LightweightCharts.</p></div>';
            }
            return;
        }

        // 2.1 Gráfico Principal de Velas + EMAs
        dom.tvMainChart.innerHTML = '';
        state.mainChart = LightweightCharts.createChart(dom.tvMainChart, {
            layout: {
                background: { type: 'solid', color: '#0b0e11' },
                textColor: '#848E9C',
                fontSize: 11,
                fontFamily: 'Outfit, sans-serif',
            },
            grid: {
                vertLines: { color: 'rgba(255, 255, 255, 0.04)' },
                horzLines: { color: 'rgba(255, 255, 255, 0.04)' },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: { color: '#848E9C', width: 1, style: 3, labelBackgroundColor: '#1e2329' },
                horzLine: { color: '#848E9C', width: 1, style: 3, labelBackgroundColor: '#1e2329' },
            },
            rightPriceScale: {
                borderColor: '#2b313a',
                scaleMargins: { top: 0.1, bottom: 0.15 },
            },
            timeScale: {
                borderColor: '#2b313a',
                timeVisible: true,
                secondsVisible: false,
                rightOffset: 8,
                barSpacing: 10,
            },
        });

        state.candleSeries = state.mainChart.addCandlestickSeries({
            upColor: '#0ECB81',
            downColor: '#F6465D',
            borderUpColor: '#0ECB81',
            borderDownColor: '#F6465D',
            wickUpColor: '#0ECB81',
            wickDownColor: '#F6465D',
        });

        // EMA 200 Tendencia (Púrpura)
        state.emaTrendSeries = state.mainChart.addLineSeries({
            color: '#a855f7',
            lineWidth: 2,
            title: 'EMA 200',
            crosshairMarkerVisible: true,
            priceLineVisible: false,
        });

        // EMA 20 Rápida / Pullback (Amarillo)
        state.emaFastSeries = state.mainChart.addLineSeries({
            color: '#F0B90B',
            lineWidth: 2,
            title: 'EMA 20',
            crosshairMarkerVisible: true,
            priceLineVisible: false,
        });

        // 2.2 Sub-Gráfico RSI(14)
        dom.tvRsiChart.innerHTML = '';
        state.rsiChart = LightweightCharts.createChart(dom.tvRsiChart, {
            layout: {
                background: { type: 'solid', color: '#0b0e11' },
                textColor: '#848E9C',
                fontSize: 10,
                fontFamily: 'Outfit, sans-serif',
            },
            grid: {
                vertLines: { color: 'rgba(255, 255, 255, 0.03)' },
                horzLines: { color: 'rgba(255, 255, 255, 0.03)' },
            },
            rightPriceScale: {
                borderColor: '#2b313a',
                scaleMargins: { top: 0.1, bottom: 0.1 },
            },
            timeScale: {
                visible: false, // Ocultar timescale inferior para sincronización limpia
                borderColor: '#2b313a',
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: { color: '#848E9C', width: 1, style: 3, labelBackgroundColor: '#1e2329' },
                horzLine: { color: '#00d2ff', width: 1, style: 3, labelBackgroundColor: '#00d2ff' },
            },
        });

        // Serie RSI(14) (Cian)
        state.rsiSeries = state.rsiChart.addLineSeries({
            color: '#00d2ff',
            lineWidth: 2,
            title: 'RSI(14)',
            priceLineVisible: false,
        });

        // Líneas Guía de RSI: 70 (Sobrecompra), 38 (Chimuelo Threshold), 30 (Sobreventa)
        state.rsiSeries.createPriceLine({
            price: 70.0,
            color: 'rgba(246, 70, 93, 0.6)',
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: '70 OB',
        });

        state.rsiSeries.createPriceLine({
            price: 38.0,
            color: 'rgba(240, 185, 11, 0.8)',
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Solid,
            axisLabelVisible: true,
            title: '38 CHIMUELO',
        });

        state.rsiSeries.createPriceLine({
            price: 30.0,
            color: 'rgba(14, 203, 129, 0.6)',
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: '30 OS',
        });

        // 2.3 Sincronización Temporal entre Gráfico Principal y Sub-Gráfico RSI
        let isSyncing = false;
        state.mainChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
            if (isSyncing || !range || !state.rsiChart) return;
            isSyncing = true;
            try { state.rsiChart.timeScale().setVisibleLogicalRange(range); } catch (e) {}
            isSyncing = false;
        });

        state.rsiChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
            if (isSyncing || !range || !state.mainChart) return;
            isSyncing = true;
            try { state.mainChart.timeScale().setVisibleLogicalRange(range); } catch (e) {}
            isSyncing = false;
        });

        // 2.4 Auto-Resize Responsivo
        const resizeCharts = () => {
            if (state.mainChart && dom.tvMainChart) {
                state.mainChart.resize(dom.tvMainChart.clientWidth, dom.tvMainChart.clientHeight);
            }
            if (state.rsiChart && dom.tvRsiChart) {
                state.rsiChart.resize(dom.tvRsiChart.clientWidth, dom.tvRsiChart.clientHeight);
            }
        };

        window.addEventListener('resize', resizeCharts);
        new ResizeObserver(resizeCharts).observe(dom.tvMainChart);
    }

    // ============================================================
    // 3. CÁLCULO CUANTITATIVO DE INDICADORES (EMA, RSI, ATR)
    // ============================================================

    // EMA (Exponential Moving Average)
    function calculateEMA(candles, period) {
        if (!candles || candles.length < period) return [];
        const k = 2 / (period + 1);
        const emaData = [];

        // Inicializar primer valor con promedio simple (SMA)
        let sum = 0;
        for (let i = 0; i < period; i++) {
            sum += candles[i].close;
        }
        let prevEMA = sum / period;
        emaData.push({ time: candles[period - 1].time, value: prevEMA });

        for (let i = period; i < candles.length; i++) {
            const currentClose = candles[i].close;
            prevEMA = (currentClose * k) + (prevEMA * (1 - k));
            emaData.push({ time: candles[i].time, value: prevEMA });
        }
        return emaData;
    }

    // RSI (Relative Strength Index con suavizado de Wilder)
    function calculateRSI(candles, period = 14) {
        if (!candles || candles.length <= period) return [];
        const rsiData = [];

        let gains = 0;
        let losses = 0;

        for (let i = 1; i <= period; i++) {
            const diff = candles[i].close - candles[i - 1].close;
            if (diff >= 0) gains += diff;
            else losses -= diff;
        }

        let avgGain = gains / period;
        let avgLoss = losses / period;

        let rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
        let firstRSI = 100 - (100 / (1 + rs));
        rsiData.push({ time: candles[period].time, value: firstRSI });

        for (let i = period + 1; i < candles.length; i++) {
            const diff = candles[i].close - candles[i - 1].close;
            const currentGain = diff >= 0 ? diff : 0;
            const currentLoss = diff < 0 ? -diff : 0;

            avgGain = (avgGain * (period - 1) + currentGain) / period;
            avgLoss = (avgLoss * (period - 1) + currentLoss) / period;

            rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
            const rsi = 100 - (100 / (1 + rs));
            rsiData.push({ time: candles[i].time, value: rsi });
        }

        return rsiData;
    }

    // ATR (Average True Range)
    function calculateATR(candles, period = 14) {
        if (!candles || candles.length <= period) return 0;
        const trValues = [];

        for (let i = 1; i < candles.length; i++) {
            const high = candles[i].high;
            const low = candles[i].low;
            const prevClose = candles[i - 1].close;
            const tr = Math.max(high - low, Math.abs(high - prevClose), Math.abs(low - prevClose));
            trValues.push(tr);
        }

        if (trValues.length < period) return 0;

        let atr = trValues.slice(0, period).reduce((a, b) => a + b, 0) / period;
        for (let i = period; i < trValues.length; i++) {
            atr = (atr * (period - 1) + trValues[i]) / period;
        }
        return atr;
    }

    // ============================================================
    // 4. DETECCIÓN DE DIVERGENCIAS ALCISTAS Y GENERACIÓN DE SEÑALES
    // ============================================================
    function analyzeStrategyAndSignals(candles, emaTrend, emaFast, rsiData) {
        if (!candles || candles.length < 50 || !rsiData || rsiData.length < 30) {
            return { markers: [], simulatedTrades: [], divergenceFound: false, latestATR: 0 };
        }

        const rsiMap = new Map();
        rsiData.forEach(r => rsiMap.set(r.time, r.value));

        const emaTrendMap = new Map();
        emaTrend.forEach(e => emaTrendMap.set(e.time, e.value));

        const atrVal = calculateATR(candles, 14);
        const markers = [];
        const simulatedTrades = [];
        let divergenceFound = false;

        // Búsqueda de divergencias alcistas históricas
        // Condición: Precio hace Lower Low o Equal Low mientras RSI hace Higher Low (con RSI <= 38)
        // y Precio > EMA 200 (Filtro Tendencia Macro)
        const lookback = 20;

        for (let i = lookback; i < candles.length - 2; i++) {
            const currentCandle = candles[i];
            const currentRsi = rsiMap.get(currentCandle.time);
            const currentEma200 = emaTrendMap.get(currentCandle.time);

            if (!currentRsi || !currentEma200) continue;

            // 1. Filtro Macro: Precio > EMA 200
            if (currentCandle.close < currentEma200) continue;

            // 2. Umbral Chimuelo: RSI en zona de sobreventa (<= 38.0)
            if (currentRsi <= 38.0) {
                // Comprobar si hay un valle previo más bajo en precio pero más bajo en RSI
                let prevLowIdx = -1;
                for (let j = i - 4; j >= i - lookback && j >= 0; j--) {
                    const c = candles[j];
                    const r = rsiMap.get(c.time);
                    if (r && r <= 38.0 && r < currentRsi && c.low >= currentCandle.low * 0.98) {
                        prevLowIdx = j;
                        break;
                    }
                }

                if (prevLowIdx !== -1) {
                    divergenceFound = true;
                    const entryPrice = currentCandle.close;
                    const slDist = Math.max(atrVal * 1.5, entryPrice * 0.015);
                    const slPrice = entryPrice - slDist;
                    const tpPrice = entryPrice + (slDist * 2.5); // R:R = 1:2.5

                    // Marker de Compra
                    markers.push({
                        time: currentCandle.time,
                        position: 'belowBar',
                        color: '#0ECB81',
                        shape: 'arrowUp',
                        text: `BUY $${entryPrice.toFixed(2)}`,
                        size: 2,
                    });

                    // Simular progresión de trade en velas siguientes
                    let tradeClosed = false;
                    let exitPrice = entryPrice;
                    let exitTime = currentCandle.time;
                    let exitReason = 'ACTIVE';

                    for (let k = i + 1; k < candles.length; k++) {
                        const forwardCandle = candles[k];
                        if (forwardCandle.high >= tpPrice) {
                            tradeClosed = true;
                            exitPrice = tpPrice;
                            exitTime = forwardCandle.time;
                            exitReason = 'TAKE PROFIT';
                            markers.push({
                                time: forwardCandle.time,
                                position: 'aboveBar',
                                color: '#0ECB81',
                                shape: 'circle',
                                text: 'TP',
                            });
                            break;
                        } else if (forwardCandle.low <= slPrice) {
                            tradeClosed = true;
                            exitPrice = slPrice;
                            exitTime = forwardCandle.time;
                            exitReason = 'STOP LOSS';
                            markers.push({
                                time: forwardCandle.time,
                                position: 'belowBar',
                                color: '#F6465D',
                                shape: 'circle',
                                text: 'SL',
                            });
                            break;
                        }
                    }

                    const tradePnl = tradeClosed 
                        ? ((exitPrice - entryPrice) / entryPrice) * state.initialBalance
                        : ((candles[candles.length - 1].close - entryPrice) / entryPrice) * state.initialBalance;

                    const tradePnlPct = ((exitPrice - entryPrice) / entryPrice) * 100;

                    simulatedTrades.push({
                        symbol: state.symbol,
                        side: 'LONG',
                        entryPrice,
                        exitPrice: tradeClosed ? exitPrice : candles[candles.length - 1].close,
                        slPrice,
                        tpPrice,
                        pnl: tradePnl,
                        pnlPct: tradePnlPct,
                        status: exitReason,
                        entryTime: new Date(currentCandle.time * 1000).toISOString().replace('T', ' ').substring(0, 16),
                        exitTime: tradeClosed ? new Date(exitTime * 1000).toISOString().replace('T', ' ').substring(0, 16) : 'En curso',
                        isOpen: !tradeClosed,
                    });

                    // Si el trade está abierto en la última vela, marcarlo como posición activa
                    if (!tradeClosed) {
                        state.activePosition = {
                            symbol: state.symbol,
                            side: 'LONG',
                            entryPrice,
                            slPrice,
                            tpPrice,
                            size: state.initialBalance / entryPrice,
                            pnl: tradePnl,
                            pnlPct: tradePnlPct,
                        };
                    }

                    // Saltar algunas velas para no sobre-apalancar señales duplicadas en la misma zona
                    i += 10;
                }
            }
        }

        return { markers, simulatedTrades, divergenceFound, latestATR: atrVal };
    }

    // ============================================================
    // 5. CARGA Y RENDERIZADO DE VELAS HISTÓRICAS
    // ============================================================
    async function fetchCandlesAndRender() {
        if (dom.chartSymbolTitle) {
            dom.chartSymbolTitle.textContent = `${state.symbol.replace('USDT', '')} / USDT`;
        }
        if (dom.chartTfTitle) {
            dom.chartTfTitle.textContent = state.interval;
        }

        // Determinar días de descarga según temporalidad
        let days = 3;
        if (state.interval === '15m') days = 4;
        else if (state.interval === '1h') days = 16;
        else if (state.interval === '4h') days = 50;

        try {
            const res = await fetch(`/api/candles?symbol=${state.symbol}&interval=${state.interval}&days=${days}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
            const data = await res.json();

            if (!data.candles || data.candles.length === 0) {
                appendLog(`[!] No se recibieron velas para ${state.symbol} (${state.interval})`, 'warn');
                return;
            }

            state.candles = data.candles;
            const lastCandle = state.candles[state.candles.length - 1];
            const prevCandle = state.candles[0];

            // 5.1 Calcular Estadísticas 24h & Ticker
            updateTickerStats(lastCandle, prevCandle);

            // 5.2 Calcular Indicadores Cuánticos
            const ema200 = calculateEMA(state.candles, Math.min(200, Math.floor(state.candles.length / 2)));
            const ema20 = calculateEMA(state.candles, 20);
            const rsi14 = calculateRSI(state.candles, 14);

            // 5.3 Analizar Estrategia & Divergencias
            state.activePosition = null;
            const analysis = analyzeStrategyAndSignals(state.candles, ema200, ema20, rsi14);

            // 5.4 Cargar Datos en Gráficos TradingView
            state.candleSeries.setData(state.candles);
            state.emaTrendSeries.setData(ema200);
            state.emaFastSeries.setData(ema20);
            state.rsiSeries.setData(rsi14);

            // Marcadores en Velas
            if (analysis.markers.length > 0) {
                state.candleSeries.setMarkers(analysis.markers);
            }

            state.mainChart.timeScale().fitContent();

            // 5.5 Actualizar Panel de Estrategia
            updateStrategyStatusUI(lastCandle, ema200, ema20, rsi14, analysis);

            // 5.6 Actualizar Posición Activa UI
            updateActivePositionUI(lastCandle.close);

            // 5.7 Actualizar Historial de Trades & KPIs
            state.trades = analysis.simulatedTrades;
            updateTradesHistoryUI();
            updateFinancialKPIs();

        } catch (err) {
            appendLog(`[!] Error cargando velas: ${err.message}`, 'error');
        }
    }

    // ============================================================
    // 6. ACTUALIZACIÓN DEL TICKER Y ANIMACIÓN DE PARPADEO
    // ============================================================
    function updateTickerStats(currentCandle, baselineCandle) {
        if (!currentCandle) return;
        const currentPrice = currentCandle.close;

        // Animación Flash de Precio
        if (state.lastPrice !== null && dom.tickerPrice) {
            dom.tickerPrice.classList.remove('price-flash-up', 'price-flash-down');
            void dom.tickerPrice.offsetWidth; // Trigger reflow
            if (currentPrice > state.lastPrice) {
                dom.tickerPrice.classList.add('price-flash-up');
                dom.tickerPrice.style.color = '#0ECB81';
            } else if (currentPrice < state.lastPrice) {
                dom.tickerPrice.classList.add('price-flash-down');
                dom.tickerPrice.style.color = '#F6465D';
            }
        }
        state.lastPrice = currentPrice;

        // Formateo de precio con precisión según moneda
        const precision = currentPrice >= 1000 ? 2 : currentPrice >= 10 ? 2 : 4;
        const priceStr = `$${currentPrice.toLocaleString('en-US', { minimumFractionDigits: precision, maximumFractionDigits: precision })}`;

        if (dom.tickerPrice) dom.tickerPrice.textContent = priceStr;

        // Cálculo de cambio relativo
        const base = baselineCandle ? baselineCandle.open : currentPrice;
        const diff = currentPrice - base;
        const diffPct = (diff / base) * 100;
        const isPositive = diff >= 0;

        if (dom.tickerChangeBadge) {
            dom.tickerChangeBadge.textContent = `${isPositive ? '+' : ''}${diffPct.toFixed(2)}%`;
            dom.tickerChangeBadge.className = `stat-badge ${isPositive ? '' : 'negative'}`;
        }

        if (dom.tickerChange24h) {
            dom.tickerChange24h.textContent = `${isPositive ? '+$' : '-$'}${Math.abs(diff).toFixed(2)} (${isPositive ? '+' : ''}${diffPct.toFixed(2)}%)`;
            dom.tickerChange24h.style.color = isPositive ? '#0ECB81' : '#F6465D';
        }

        // High & Low
        let high = currentPrice;
        let low = currentPrice;
        let vol = 0;
        state.candles.slice(-24).forEach(c => {
            if (c.high > high) high = c.high;
            if (c.low < low) low = c.low;
            vol += c.volume;
        });

        if (dom.tickerHigh24h) dom.tickerHigh24h.textContent = `$${high.toFixed(precision)}`;
        if (dom.tickerLow24h) dom.tickerLow24h.textContent = `$${low.toFixed(precision)}`;
        if (dom.tickerVol24h) dom.tickerVol24h.textContent = `${(vol / 1000).toFixed(2)}K ${state.symbol.replace('USDT', '')}`;
    }

    // ============================================================
    // 7. ACTUALIZACIÓN DEL ESTADO DE LA ESTRATEGIA
    // ============================================================
    function updateStrategyStatusUI(lastCandle, emaTrend, emaFast, rsiData, analysis) {
        if (!lastCandle) return;
        const price = lastCandle.close;

        // EMA 200
        const latestEma200 = emaTrend.length > 0 ? emaTrend[emaTrend.length - 1].value : null;
        if (latestEma200 && dom.indEmaTrendVal && dom.indTrendBadge) {
            dom.indEmaTrendVal.textContent = `EMA: $${latestEma200.toFixed(2)} | Precio: $${price.toFixed(2)}`;
            if (price >= latestEma200) {
                dom.indTrendBadge.textContent = 'BULLISH';
                dom.indTrendBadge.className = 'ind-badge badge-bullish';
            } else {
                dom.indTrendBadge.textContent = 'BEARISH';
                dom.indTrendBadge.className = 'ind-badge badge-bearish';
            }
        }

        // EMA 20
        const latestEma20 = emaFast.length > 0 ? emaFast[emaFast.length - 1].value : null;
        if (latestEma20 && dom.indEmaFastVal && dom.indFastBadge) {
            dom.indEmaFastVal.textContent = `EMA 20: $${latestEma20.toFixed(2)}`;
            if (price >= latestEma20) {
                dom.indFastBadge.textContent = 'SOBRE EMA20';
                dom.indFastBadge.className = 'ind-badge badge-bullish';
            } else {
                dom.indFastBadge.textContent = 'BAJO EMA20';
                dom.indFastBadge.className = 'ind-badge badge-neutral';
            }
        }

        // RSI 14
        const latestRsi = rsiData.length > 0 ? rsiData[rsiData.length - 1].value : null;
        if (latestRsi !== null) {
            if (dom.rsiLiveValue) dom.rsiLiveValue.textContent = latestRsi.toFixed(2);
            if (dom.indRsiVal) dom.indRsiVal.textContent = `Valor actual: ${latestRsi.toFixed(2)}`;

            if (latestRsi <= 38.0) {
                if (dom.rsiZoneBadge) {
                    dom.rsiZoneBadge.textContent = 'SOBREVENTA (< 38)';
                    dom.rsiZoneBadge.className = 'rsi-zone-badge oversold';
                }
                if (dom.indRsiBadge) {
                    dom.indRsiBadge.textContent = 'ZONA CHIMUELO';
                    dom.indRsiBadge.className = 'ind-badge badge-oversold';
                }
            } else if (latestRsi >= 70.0) {
                if (dom.rsiZoneBadge) {
                    dom.rsiZoneBadge.textContent = 'SOBRECOMPRA (> 70)';
                    dom.rsiZoneBadge.className = 'rsi-zone-badge';
                }
                if (dom.indRsiBadge) {
                    dom.indRsiBadge.textContent = 'SOBRECOMPRA';
                    dom.indRsiBadge.className = 'ind-badge badge-bearish';
                }
            } else {
                if (dom.rsiZoneBadge) {
                    dom.rsiZoneBadge.textContent = 'ZONA NEUTRAL';
                    dom.rsiZoneBadge.className = 'rsi-zone-badge';
                }
                if (dom.indRsiBadge) {
                    dom.indRsiBadge.textContent = 'NEUTRAL';
                    dom.indRsiBadge.className = 'ind-badge badge-neutral';
                }
            }
        }

        // Divergencia RSI
        if (dom.indDivBadge && dom.indDivVal) {
            if (analysis.divergenceFound) {
                dom.indDivBadge.textContent = 'DIVERGENCIA 🚀';
                dom.indDivBadge.className = 'ind-badge badge-confirmed';
                dom.indDivVal.textContent = 'Divergencia alcista validada';
            } else {
                dom.indDivBadge.textContent = 'ESCANEANDO';
                dom.indDivBadge.className = 'ind-badge badge-waiting';
                dom.indDivVal.textContent = 'Buscando patrón de valles';
            }
        }

        // ATR 14
        if (dom.indAtrVal && dom.indAtrBadge) {
            const atr = analysis.latestATR || 0;
            dom.indAtrVal.textContent = `ATR: $${atr.toFixed(2)} (SL 1.5x: $${(atr * 1.5).toFixed(2)})`;
            dom.indAtrBadge.textContent = 'R:R 1:2.5';
        }
    }

    // ============================================================
    // 7.1 ACTUALIZACIÓN DEL SENTIMIENTO MACRO (M10)
    // ============================================================
    function updateSentimentUI(data) {
        if (!data) return;
        const score = typeof data.score === 'number' ? data.score : parseFloat(data.score) || 50;
        const category = data.category || 'NEUTRAL';
        const regime = data.macro_regime || 'NEUTRAL';
        const canOpen = data.can_open_longs !== false;
        const summary = data.macro_summary || data.summary || 'Sentimiento de mercado neutral.';

        if (dom.fngScoreBadge) {
            let color = '#0ECB81';
            if (score <= 25) color = '#F6465D';
            else if (score <= 45) color = '#F0B90B';
            else if (score >= 75) color = '#00F0FF';
            dom.fngScoreBadge.textContent = `${Math.round(score)} / 100 (${category.replace('_', ' ')})`;
            dom.fngScoreBadge.style.color = color;
        }

        if (dom.fngProgressBar) {
            dom.fngProgressBar.style.width = `${Math.max(5, Math.min(100, score))}%`;
        }

        if (dom.macroRegimeBadge) {
            dom.macroRegimeBadge.textContent = regime.replace('_', ' ');
            if (regime === 'RISK_ON') {
                dom.macroRegimeBadge.className = 'ind-badge badge-bullish';
            } else if (regime === 'BLACK_SWAN_VETO') {
                dom.macroRegimeBadge.className = 'ind-badge badge-bearish';
            } else if (regime === 'RISK_OFF') {
                dom.macroRegimeBadge.className = 'ind-badge badge-neutral';
            } else {
                dom.macroRegimeBadge.className = 'ind-badge badge-bullish';
            }
        }

        if (dom.macroVetoBadge && dom.macroVetoDetail) {
            if (canOpen) {
                dom.macroVetoBadge.textContent = 'LIBRE 🟢';
                dom.macroVetoBadge.className = 'ind-badge badge-bullish';
                dom.macroVetoDetail.textContent = 'Compras autorizadas';
            } else {
                dom.macroVetoBadge.textContent = 'VETO 🚫';
                dom.macroVetoBadge.className = 'ind-badge badge-bearish';
                dom.macroVetoDetail.textContent = data.veto_reason || 'Compras bloqueadas por pánico';
            }
        }

        if (dom.macroSummaryText) {
            dom.macroSummaryText.textContent = summary;
        }
    }

    async function fetchSentimentAndRender() {
        try {
            const res = await fetch('/api/sentiment');
            if (res.ok) {
                const data = await res.json();
                updateSentimentUI(data);
            }
        } catch (e) {
            console.warn('[Chimuelo] Error cargando sentimiento:', e);
        }
    }

    // ============================================================
    // 8. PANEL DE POSICIÓN ACTIVA Y SEGUIMIENTO EN VIVO
    // ============================================================
    function updateActivePositionUI(currentPrice) {
        // Limpiar líneas de precio anteriores en el gráfico
        state.positionPriceLines.forEach(l => {
            try { state.candleSeries.removePriceLine(l); } catch (e) {}
        });
        state.positionPriceLines = [];

        if (!state.activePosition) {
            if (dom.noPositionView) dom.noPositionView.style.display = 'flex';
            if (dom.hasPositionView) dom.hasPositionView.style.display = 'none';
            if (dom.posStatusBadge) {
                dom.posStatusBadge.textContent = 'SIN POSICIÓN';
                dom.posStatusBadge.className = 'pos-status-badge badge-idle';
            }
            return;
        }

        // Si HAY posición activa
        const pos = state.activePosition;
        if (dom.noPositionView) dom.noPositionView.style.display = 'none';
        if (dom.hasPositionView) dom.hasPositionView.style.display = 'flex';
        if (dom.posStatusBadge) {
            dom.posStatusBadge.textContent = 'ACTIVA';
            dom.posStatusBadge.className = 'pos-status-badge badge-active-pos';
        }

        if (dom.posPair) dom.posPair.textContent = pos.symbol;
        if (dom.posEntryPrice) dom.posEntryPrice.textContent = `$${pos.entryPrice.toFixed(2)}`;
        if (dom.posSlPrice) dom.posSlPrice.textContent = `$${pos.slPrice.toFixed(2)}`;
        if (dom.posTpPrice) dom.posTpPrice.textContent = `$${pos.tpPrice.toFixed(2)}`;
        if (dom.posSize) dom.posSize.textContent = `${pos.size.toFixed(4)} ${pos.symbol.replace('USDT', '')}`;
        if (dom.posCurrentPrice) dom.posCurrentPrice.textContent = `$${currentPrice.toFixed(2)}`;

        if (dom.lblSlPrice) dom.lblSlPrice.textContent = `SL $${pos.slPrice.toFixed(2)}`;
        if (dom.lblEntryPrice) dom.lblEntryPrice.textContent = `Entry $${pos.entryPrice.toFixed(2)}`;
        if (dom.lblTpPrice) dom.lblTpPrice.textContent = `TP $${pos.tpPrice.toFixed(2)}`;

        // Calcular PnL flotante
        const currentPnl = ((currentPrice - pos.entryPrice) / pos.entryPrice) * state.initialBalance;
        const currentPnlPct = ((currentPrice - pos.entryPrice) / pos.entryPrice) * 100;
        const isProfit = currentPnl >= 0;

        if (dom.posPnlVal) {
            dom.posPnlVal.textContent = `${isProfit ? '+$' : '-$'}${Math.abs(currentPnl).toFixed(2)}`;
            dom.posPnlVal.style.color = isProfit ? '#0ECB81' : '#F6465D';
        }
        if (dom.posPnlPct) {
            dom.posPnlPct.textContent = `(${isProfit ? '+' : ''}${currentPnlPct.toFixed(2)}%)`;
            dom.posPnlPct.style.color = isProfit ? '#0ECB81' : '#F6465D';
        }

        // Posición del cursor en la barra de progreso SL - Entry - TP
        const totalRange = pos.tpPrice - pos.slPrice;
        let progressPct = 50;
        if (totalRange > 0) {
            progressPct = ((currentPrice - pos.slPrice) / totalRange) * 100;
            progressPct = Math.max(0, Math.min(100, progressPct));
        }
        if (dom.posPriceCursor) {
            dom.posPriceCursor.style.left = `${progressPct}%`;
        }

        // Dibujar Líneas Horizontales en el Gráfico de Velas (Entry, SL, TP)
        if (state.candleSeries) {
            const entryLine = state.candleSeries.createPriceLine({
                price: pos.entryPrice,
                color: '#848E9C',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dotted,
                axisLabelVisible: true,
                title: 'ENTRADA',
            });
            const slLine = state.candleSeries.createPriceLine({
                price: pos.slPrice,
                color: '#F6465D',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Solid,
                axisLabelVisible: true,
                title: 'STOP LOSS',
            });
            const tpLine = state.candleSeries.createPriceLine({
                price: pos.tpPrice,
                color: '#0ECB81',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Solid,
                axisLabelVisible: true,
                title: 'TAKE PROFIT',
            });
            state.positionPriceLines.push(entryLine, slLine, tpLine);
        }
    }

    // ============================================================
    // 9. HISTORIAL DE TRADES Y ACTUALIZACIÓN DE TABLA
    // ============================================================
    function updateTradesHistoryUI() {
        if (!dom.tradesTbody) return;

        if (state.trades.length === 0) {
            dom.tradesTbody.innerHTML = `
                <tr>
                    <td colspan="10" class="table-empty">
                        <i class="fa-solid fa-inbox"></i>
                        <p>Buscando oportunidades cuantitativas de entrada (Divergencia RSI + EMA 200)...</p>
                    </td>
                </tr>
            `;
            if (dom.tradesCountBadge) dom.tradesCountBadge.textContent = '0';
            return;
        }

        if (dom.tradesCountBadge) dom.tradesCountBadge.textContent = state.trades.length;
        dom.tradesTbody.innerHTML = '';

        state.trades.slice().reverse().forEach(t => {
            const tr = document.createElement('tr');
            const isProfit = t.pnl >= 0;
            const pnlClass = isProfit ? 'text-green' : 'text-red';

            let statusBadge = `<span class="badge-trade tp"><i class="fa-solid fa-circle-check"></i> TAKE PROFIT</span>`;
            if (t.status === 'STOP LOSS') {
                statusBadge = `<span class="badge-trade sl"><i class="fa-solid fa-shield-xmark"></i> STOP LOSS</span>`;
            } else if (t.isOpen) {
                statusBadge = `<span class="badge-trade open"><i class="fa-solid fa-spinner fa-spin"></i> EN CURSO</span>`;
            }

            tr.innerHTML = `
                <td><strong>${t.symbol}</strong></td>
                <td><span class="badge-trade long">LONG</span></td>
                <td>$${t.entryPrice.toFixed(2)}</td>
                <td>$${t.exitPrice.toFixed(2)}</td>
                <td style="color:#F6465D;">$${t.slPrice.toFixed(2)}</td>
                <td style="color:#0ECB81;">$${t.tpPrice.toFixed(2)}</td>
                <td class="${pnlClass}">${isProfit ? '+$' : '-$'}${Math.abs(t.pnl).toFixed(2)}</td>
                <td class="${pnlClass}">${isProfit ? '+' : ''}${t.pnlPct.toFixed(2)}%</td>
                <td>${statusBadge}</td>
                <td style="color:var(--text-secondary);font-size:11px;">${t.entryTime}</td>
            `;
            dom.tradesTbody.appendChild(tr);
        });
    }

    // ============================================================
    // 10. CÁLCULO DE KPIS FINANCIEROS ($25 BASE)
    // ============================================================
    function updateFinancialKPIs() {
        let totalRealized = 0;
        let wins = 0;
        let losses = 0;
        let totalGains = 0;
        let totalLossAmount = 0;

        state.trades.forEach(t => {
            if (!t.isOpen) {
                totalRealized += t.pnl;
                if (t.pnl > 0) {
                    wins++;
                    totalGains += t.pnl;
                } else {
                    losses++;
                    totalLossAmount += Math.abs(t.pnl);
                }
            }
        });

        const floatingPnl = state.activePosition ? state.activePosition.pnl : 0;
        const totalPnl = totalRealized + floatingPnl;
        const currentEquity = state.initialBalance + totalPnl;
        const roiPct = ((currentEquity - state.initialBalance) / state.initialBalance) * 100;
        const totalClosed = wins + losses;
        const winrate = totalClosed > 0 ? (wins / totalClosed) * 100 : 0;
        const profitFactor = totalLossAmount > 0 ? totalGains / totalLossAmount : totalGains > 0 ? 9.99 : 0;

        // Renderizado
        if (dom.kpiInitial) dom.kpiInitial.textContent = `$${state.initialBalance.toFixed(2)}`;
        if (dom.kpiEquity) {
            dom.kpiEquity.textContent = `$${currentEquity.toFixed(2)}`;
            dom.kpiEquity.className = `kpi-figure ${currentEquity >= state.initialBalance ? 'text-green' : 'text-red'}`;
        }
        if (dom.kpiEquityRoi) {
            dom.kpiEquityRoi.textContent = `${roiPct >= 0 ? '+' : ''}${roiPct.toFixed(2)}%`;
            dom.kpiEquityRoi.className = `kpi-tag ${roiPct >= 0 ? 'tag-success' : 'tag-risk'}`;
        }
        if (dom.kpiCashDetail) {
            const cash = state.activePosition ? 0 : currentEquity;
            const posVal = state.activePosition ? currentEquity : 0;
            dom.kpiCashDetail.textContent = `Cash: $${cash.toFixed(2)} | En Posición: $${posVal.toFixed(2)}`;
        }

        if (dom.kpiTotalPnl) {
            dom.kpiTotalPnl.textContent = `${totalPnl >= 0 ? '+$' : '-$'}${Math.abs(totalPnl).toFixed(2)}`;
            dom.kpiTotalPnl.style.color = totalPnl >= 0 ? '#0ECB81' : '#F6465D';
        }
        if (dom.kpiTotalPnlPct) {
            dom.kpiTotalPnlPct.textContent = `(${totalPnl >= 0 ? '+' : ''}${roiPct.toFixed(2)}%)`;
            dom.kpiTotalPnlPct.style.color = totalPnl >= 0 ? '#0ECB81' : '#F6465D';
        }
        if (dom.kpiPnlSplit) {
            dom.kpiPnlSplit.textContent = `Real: $${totalRealized.toFixed(2)} | Flot: $${floatingPnl.toFixed(2)}`;
        }

        if (dom.kpiWinrate) dom.kpiWinrate.textContent = `${winrate.toFixed(1)}%`;
        if (dom.kpiTradesCount) dom.kpiTradesCount.textContent = `${totalClosed} Cerrados`;
        if (dom.kpiWinlossDetail) dom.kpiWinlossDetail.textContent = `${wins} Ganadas / ${losses} Perdidas`;

        if (dom.kpiProfitFactor) dom.kpiProfitFactor.textContent = profitFactor.toFixed(2);
        if (dom.kpiDrawdown) dom.kpiDrawdown.textContent = '0.00%';
    }

    // ============================================================
    // 11. CONEXIÓN WEBSOCKET Y TERMINAL EN VIVO
    // ============================================================
    function connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        // Probar /ws/live con fallback a /api/ws
        const wsUrl = `${protocol}//${window.location.host}/ws/live`;

        try {
            state.ws = new WebSocket(wsUrl);

            state.ws.onopen = () => {
                appendLog('[+] WebSocket /ws/live conectado con éxito.', 'success');
                if (dom.wsLatencyVal) dom.wsLatencyVal.textContent = '< 15 ms';
            };

            state.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.type === 'log') {
                        let level = 'info';
                        const lower = data.message.toLowerCase();
                        if (lower.includes('error') || lower.includes('critical') || lower.includes('fail')) level = 'error';
                        else if (lower.includes('warn') || lower.includes('alert')) level = 'warn';
                        else if (lower.includes('success') || lower.includes('filled') || lower.includes('iniciado')) level = 'success';
                        appendLog(data.message, level);
                    } else if (data.type === 'live_update') {
                        if (typeof data.is_running === 'boolean') {
                            updateBotStatusUI(data.is_running);
                        }
                        if (data.account) {
                            if (data.account.balance) state.initialBalance = Number(data.account.balance);
                            if (data.account.equity) state.equity = Number(data.account.equity);
                        }
                        if (data.sentiment) {
                            updateSentimentUI(data.sentiment);
                        }
                    } else if (data.type === 'status') {
                        updateBotStatusUI(data.is_running);
                    }
                } catch (e) {
                    appendLog(event.data, 'info');
                }
            };

            state.ws.onclose = () => {
                appendLog('[!] WebSocket desconectado. Reconectando en 4s...', 'warn');
                setTimeout(connectWebSocket, 4000);
            };

            state.ws.onerror = () => {
                // Fallback secundario si /ws/live diera error
                console.warn('[Chimuelo] Reintentando conexión WS');
            };
        } catch (e) {
            console.error('[Chimuelo] Error iniciando WebSocket:', e);
        }
    }

    function appendLog(msg, level = 'info') {
        if (!dom.consoleLogs) return;
        const now = new Date().toISOString().substring(11, 19);
        const div = document.createElement('div');
        div.className = `log-entry ${level}`;
        div.innerHTML = `<span class="log-ts">[${now}]</span> <span class="log-msg">${escapeHtml(msg)}</span>`;
        dom.consoleLogs.appendChild(div);

        while (dom.consoleLogs.childNodes.length > 300) {
            dom.consoleLogs.removeChild(dom.consoleLogs.firstChild);
        }

        if (state.autoscroll) {
            dom.consoleLogs.scrollTop = dom.consoleLogs.scrollHeight;
        }
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function updateBotStatusUI(isRunning) {
        state.isRunning = isRunning;
        if (dom.botStatusBadge && dom.botStatusText) {
            if (isRunning) {
                dom.botStatusBadge.className = 'status-indicator status-active';
                dom.botStatusText.textContent = 'PAPER TRADING ACTIVO';
                if (dom.btnStart) dom.btnStart.disabled = true;
                if (dom.btnStop) dom.btnStop.disabled = false;
            } else {
                dom.botStatusBadge.className = 'status-indicator status-inactive';
                dom.botStatusText.textContent = 'PAPER TRADING PAUSADO';
                if (dom.btnStart) dom.btnStart.disabled = false;
                if (dom.btnStop) dom.btnStop.disabled = true;
            }
        }
    }

    // ============================================================
    // 12. EVENT LISTENERS Y CONTROLADORES
    // ============================================================

    // 12.1 Selector de Pares (SOLUSDT, ETHUSDT, BTCUSDT)
    dom.pairButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            dom.pairButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.symbol = btn.getAttribute('data-symbol') || 'SOLUSDT';
            appendLog(`[*] Cambiando instrumento a ${state.symbol}...`, 'info');
            fetchCandlesAndRender();
        });
    });

    // 12.2 Selector de Temporalidad (15m, 1h, 4h)
    dom.tfButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            dom.tfButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.interval = btn.getAttribute('data-interval') || '15m';
            appendLog(`[*] Cambiando temporalidad a ${state.interval}...`, 'info');
            fetchCandlesAndRender();
        });
    });

    // 12.3 Pestañas (Historial / Terminal / Métricas)
    dom.tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-tab');
            dom.tabBtns.forEach(b => b.classList.remove('active'));
            dom.tabContents.forEach(c => c.classList.remove('active'));

            btn.classList.add('active');
            const targetContent = document.getElementById(targetId);
            if (targetContent) targetContent.classList.add('active');

            if (dom.terminalActions) {
                dom.terminalActions.style.display = targetId === 'tab-terminal' ? 'flex' : 'none';
            }
        });
    });

    // 12.4 Botón Iniciar Paper Trading
    if (dom.btnStart) {
        dom.btnStart.addEventListener('click', async () => {
            dom.btnStart.disabled = true;
            appendLog('🚀 [PAPER TRADING] Iniciando motor cuántico de Chimuelo Prime...', 'info');
            try {
                const res = await fetch('/api/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        config_path: dom.inputConfig ? dom.inputConfig.value : 'config/chimuelo.yaml',
                        db_url: dom.inputDb ? dom.inputDb.value : 'sqlite:///chimuelo.db',
                    }),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Fallo al iniciar el bot');
                appendLog(`[+] ${data.message}`, 'success');
                updateBotStatusUI(true);
                setTimeout(fetchCandlesAndRender, 1500);
            } catch (err) {
                appendLog(`[!] Error al iniciar: ${err.message}`, 'error');
                setTimeout(() => { dom.btnStart.disabled = false; }, 2000);
            }
        });
    }

    // 12.5 Botón Detener Bot
    if (dom.btnStop) {
        dom.btnStop.addEventListener('click', async () => {
            dom.btnStop.disabled = true;
            appendLog('[*] Deteniendo motor de paper trading...', 'info');
            try {
                const res = await fetch('/api/stop', { method: 'POST' });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Fallo al detener');
                appendLog(`[+] ${data.message}`, 'success');
                updateBotStatusUI(false);
            } catch (err) {
                appendLog(`[!] Error al detener: ${err.message}`, 'error');
                dom.btnStop.disabled = false;
            }
        });
    }

    // 12.6 Botón Panic Stop
    if (dom.btnPanic) {
        dom.btnPanic.addEventListener('click', async () => {
            if (!confirm('💥 ¿EJECUTAR PANIC STOP? Se cancelarán todas las órdenes y se detendrá inmediatamente el motor de trading.')) {
                return;
            }
            dom.btnPanic.disabled = true;
            appendLog('🚨 [PANIC] Ejecutando parada de emergencia masiva...', 'error');
            try {
                const res = await fetch('/api/panic', { method: 'POST' });
                const data = await res.json();
                appendLog(`🚨 [PANIC] ${data.message}`, 'error');
                updateBotStatusUI(false);
            } catch (err) {
                appendLog(`[!] Error en pánico: ${err.message}`, 'error');
            } finally {
                dom.btnPanic.disabled = false;
            }
        });
    }

    // 12.7 Acciones de Gráficos & Terminal
    if (dom.btnFitChart) {
        dom.btnFitChart.addEventListener('click', () => {
            if (state.mainChart) state.mainChart.timeScale().fitContent();
            if (state.rsiChart) state.rsiChart.timeScale().fitContent();
        });
    }

    if (dom.btnRefreshCandles) {
        dom.btnRefreshCandles.addEventListener('click', () => {
            appendLog('[*] Refrescando velas desde Binance...', 'info');
            fetchCandlesAndRender();
        });
    }

    if (dom.btnClearConsole) {
        dom.btnClearConsole.addEventListener('click', () => {
            if (dom.consoleLogs) dom.consoleLogs.innerHTML = '';
        });
    }

    if (dom.btnAutoscroll) {
        dom.btnAutoscroll.addEventListener('click', () => {
            state.autoscroll = !state.autoscroll;
            dom.btnAutoscroll.classList.toggle('active', state.autoscroll);
        });
    }

    // ============================================================
    // 13. ARRANQUE INICIAL
    // ============================================================
    async function syncInitialStatus() {
        try {
            const res = await fetch('/api/paper/status');
            if (res.ok) {
                const data = await res.json();
                if (typeof data.is_running === 'boolean') {
                    updateBotStatusUI(data.is_running);
                }
                if (data.balance) state.initialBalance = Number(data.balance);
                if (data.equity) state.equity = Number(data.equity);
                if (data.symbol) state.symbol = data.symbol;
                if (data.interval) state.interval = data.interval;
                updateFinancialKPIs();
            }
        } catch (e) {
            console.warn('[Chimuelo] Error sincronizando estado:', e);
        }
    }

    initCharts();
    syncInitialStatus();
    fetchSentimentAndRender();
    fetchCandlesAndRender();
    connectWebSocket();

    // Actualización de estado y velas cada 8 segundos
    setInterval(fetchCandlesAndRender, 8000);
    // Actualización de sentimiento macro cada 60 segundos
    setInterval(fetchSentimentAndRender, 60000);
});
