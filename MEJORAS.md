# AlgoTrader — Análisis de Problemas y Plan de Mejora

> Documento de trabajo. Cada sección está ordenada por impacto real.
> Referencias de código: `archivo.py:línea`

---

## RESUMEN EJECUTIVO

El proyecto tiene **2 capas de problemas distintas**:

1. **Bugs reales** — cosas que están rotas ahora mismo y hacen que la app no funcione como parece que debería (el gráfico no muestra indicadores, hay código muerto, etc.)
2. **Problemas algorítmicos** — el modelo en sí mismo tiene limitaciones estructurales que limitan la rentabilidad

La prioridad es primero bugs, luego algoritmo.

---

## PARTE 1 — BUGS REALES (cosas rotas ahora mismo)

### BUG 1 ★★★ — Nombres de columnas inconsistentes: el gráfico nunca muestra indicadores

**Severidad: Alta — afecta toda la visualización**

`feature_engineer.py` genera columnas en **minúscula**:
```python
out["sma20"], out["sma50"], out["rsi"], out["bb_upper"], out["vol_sma20"]
```

Pero `chart_widget.py` busca en **mayúscula/mixta**:
```python
if "SMA20" in df.columns:   # ← nunca True
if "RSI"   in df.columns:   # ← nunca True
if "BB_upper" in df.columns: # ← nunca True
if "VOL_SMA20" in df.columns: # ← nunca True
```

Y `main_window._explain_bar()` también busca en mayúscula:
```python
row.get("RSI", None)      # ← siempre None
row.get("BB_upper", None) # ← siempre None
row.get("SMA20", None)    # ← siempre None
row.get("VOL_SMA20", None)# ← siempre None
```

**Resultado:** El gráfico muestra velas y volumen pero **nunca** las líneas SMA20/SMA50, las Bandas de Bollinger ni el panel RSI. El panel de explicación por vela también está vacío en esas secciones.

**Solución:** Estandarizar a minúscula en todas partes (es la convención de pandas). Cambiar `chart_widget.py` y `_explain_bar` para usar los nombres que genera `feature_engineer.py`.

---

### BUG 2 ★★★ — Código muerto: dos implementaciones paralelas sin conectar

**Severidad: Alta — confusión de mantenimiento y riesgo de usar el código incorrecto**

Existen DOS pipelines de análisis que hacen lo mismo:

| Archivo | Motor | Scaler | Columnas | ¿Se usa? |
|---|---|---|---|---|
| `indicators.py` + `ml_model.py` | RandomForest | StandardScaler | MAYÚSCULAS | ❌ MUERTO |
| `feature_engineer.py` + `model_trainer.py` | XGBoost | RobustScaler | minúsculas | ✅ Activo |

`indicators.py` genera exactamente las columnas que `chart_widget.py` espera (SMA20, RSI, BB_upper...) lo cual confirma que fue la implementación original. Fue reemplazada por `feature_engineer.py` pero el código viejo no se eliminó.

`trading_bot.py` solo importa `feature_engineer.py` — el par `indicators.py`/`ml_model.py` nunca se llama.

**Solución:** Eliminar `indicators.py` y `ml_model.py`. Actualizar `chart_widget.py` y `_explain_bar` para usar las columnas de `feature_engineer.py` (minúscula).

---

### BUG 3 ★★★ — Look-ahead bias en el scaler: las métricas CV están infladas

**Severidad: Alta — hace que el modelo parezca mejor de lo que es**

En `feature_engineer.py:119`:
```python
X = self.scaler.fit_transform(X_raw)  # ajusta scaler sobre TODOS los datos
```

Esto ocurre ANTES del TimeSeriesSplit. El scaler aprende la distribución de datos futuros (media, IQR de todo el histórico) y los aplica también a los datos de entrenamiento. Esto es data leakage: el modelo de cada fold "ve" estadísticas del futuro a través del scaler.

**Mismo problema** en el código muerto `indicators.py:84`.

**Efecto:** La CV accuracy reportada es artificialmente alta. El modelo real en producción rinde peor que lo que la UI muestra.

**Solución:** Ajustar el scaler DENTRO de cada fold (fit en train, transform en val), y usar ese mismo scaler para el modelo final ajustándolo sobre todos los datos solo al final.

---

### BUG 4 ★★ — Memory leak en hilos de órdenes

**Severidad: Media — se acumula con cada análisis repetido**

En `main_window.py:804`:
```python
self._order_threads.append(thread)
```

La lista `_order_threads` crece indefinidamente. Los threads terminados no se eliminan de la lista. En sesiones largas con muchos análisis, esto acumula objetos QThread muertos en memoria.

**Solución:** Conectar `thread.finished` a una función que lo elimine de la lista, o usar `_order_threads = []` al inicio de cada análisis (ya está para `_order_results` pero no para los threads).

---

### BUG 5 ★ — Texto de ConfigDialog desactualizado

**Severidad: Baja — solo confunde al usuario**

`config_dialog.py:30`:
```python
"Se guardarán en <code>Readme/config.txt</code>."
```

Desde que se migró a `.env`, las credenciales se guardan en `.env` (raíz del proyecto), no en `config.txt`. El `config.txt` solo se mantiene como legacy.

**Solución:** Actualizar el texto a "Se guardarán en `.env` en la raíz del proyecto."

---

## PARTE 2 — PROBLEMAS ALGORÍTMICOS (limitan rentabilidad)

### ALG 1 ★★★ — El target binario es casi ruido

El modelo predice: `close[t+1] > close[t]` — sí o no.

- Distribución cercana a 50/50 para cualquier acción líquida
- No distingue entre subir 0.01% y subir 3%
- Después de costes de transacción (spread + comisión ≈ 0.1% ida y vuelta), una accuracy del 55% genera pérdidas netas

**Solución:** Cambiar el target a **retorno mínimo significativo**:
```python
# En vez de close[t+1] > close[t]:
umbral = 0.005  # 0.5% mínimo de movimiento
target = (close[t+1] / close[t] - 1) > umbral  # comprar
# O usar 3 clases: subida fuerte / plano / bajada fuerte
```

---

### ALG 2 ★★★ — Sin backtesting real: no sabemos si el modelo gana dinero

La app muestra "CV Accuracy" pero eso no es P&L. Un modelo con 58% de accuracy puede perder dinero si las señales correctas son las de menor magnitud.

**Lo que falta:** un backtest que simule:
- Entrar en cada señal COMPRAR/VENDER con el precio de apertura del día siguiente
- Aplicar coste de transacción (0.05% por operación)
- Calcular equity curve, Sharpe ratio, max drawdown, win rate, profit factor

**Solución:** Añadir una pestaña "Backtest" que ejecute esto sobre el histórico y muestre la curva de capital.

---

### ALG 3 ★★ — Features puramente técnicas: están arbitradas

MACD, RSI, Bollinger son conocidos por todos. Sus patrones están arbitrados por algoritmos institucionales. No dan ventaja competitiva.

**Lo que añadiría edge real (por orden de viabilidad):**

| Feature | Dificultad | Edge esperado |
|---|---|---|
| Earnings date proximity (¿hay earnings en los próximos 5 días?) | Baja | Alto |
| Ratio put/call de opciones | Media | Alto |
| Short interest % float | Media | Medio |
| Sentimiento de noticias (NLP sobre titulares) | Media | Medio |
| Días hasta ex-dividend | Baja | Medio |

---

### ALG 4 ★★ — Sin gestión de riesgo ni position sizing

El sistema opera con `$1000 fijo por operación` independientemente de:
- La confianza del modelo (prob 65% vs prob 90%)
- La volatilidad del activo (TSLA vs JNJ)
- El balance disponible y la exposición total

**Solución mínima viable:**
```python
# Kelly fraccionado (25% del Kelly óptimo)
edge = prob_up - 0.5
kelly_fraction = 0.25
size = portfolio_value * kelly_fraction * (edge / (1 - edge))
# Además: max 5% del portfolio por posición
size = min(size, portfolio_value * 0.05)
```

---

### ALG 5 ★★ — Modelo se reentrena en cada click

Reentrenar XGBoost sobre 15 años de datos con 5 folds toma 10-30 segundos por símbolo. No tiene sentido si los datos no han cambiado significativamente (solo añadió 1 barra nueva desde ayer).

**Solución:** Usar el modelo guardado en disco si el caché de datos tiene menos de X horas y el modelo fue entrenado hoy. Solo reentrenar si el usuario fuerza o el modelo tiene más de N días.

---

### ALG 6 ★ — Datos diarios = señal tardía

La señal llega basada en el cierre de ayer. Para entrada el día siguiente hay un gap de ~16 horas entre señal y ejecución durante los cuales el mercado pre-market puede moverse.

**Solución a largo plazo:** Añadir datos intraday (1h o 15min) de Alpaca para refinar la entrada tras la señal diaria.

---

## PARTE 3 — PROBLEMAS DE DISEÑO / UX

### DIS 1 — El gráfico siempre muestra "último año" aunque el modelo entrenó desde 2010

El título dice "último año" y `DISPLAY_BARS = 252`. No hay forma de ver el histórico completo ni el periodo donde el modelo aprendió.

**Solución:** Añadir selector de rango temporal en el gráfico.

---

### DIS 2 — Sin historial de operaciones

Si cierras la app, no hay registro de qué órdenes se ejecutaron, cuándo, a qué precio. Esto hace imposible hacer seguimiento del P&L real.

**Solución:** Log de órdenes en SQLite o CSV: `orders_log.csv` en la raíz del proyecto.

---

### DIS 3 — La tabla multi-símbolo no tiene ordenación ni filtros

Con 5+ símbolos, no se puede ordenar por señal, por probabilidad, por CV accuracy.

**Solución:** Activar `QTableWidget.setSortingEnabled(True)`.

---

## PARTE 4 — PLAN DE MEJORA PRIORIZADO

### Fase 1 — Arreglar lo que está roto ✅ COMPLETADA

- [x] **BUG 1 + BUG 2**: Eliminados `indicators.py` y `ml_model.py` (código muerto — RandomForest+StandardScaler nunca usado). `chart_widget.py` y `_explain_bar` actualizados a columnas lowercase (`sma20`, `rsi`, `bb_upper`, `vol_sma20`). El gráfico ahora muestra SMA20/50, Bollinger y RSI correctamente.
- [x] **BUG 3**: Look-ahead bias corregido — `RobustScaler` se ajusta dentro de cada fold CV (fit en train, transform en val). Scaler final se ajusta sobre todos los datos solo para producción.
- [x] **BUG 4**: Memory leak `_order_threads` corregido — `thread.finished` conectado a `self._order_threads.remove(t)` para limpiar threads terminados.
- [x] **BUG 5**: `config_dialog.py` actualizado — texto cambiado de `Readme/config.txt` a `.env en la raíz del proyecto`.

### Fase 2 — Backtest real ✅ COMPLETADA

- [x] **ALG 2**: Nueva clase `Backtester` (`src/analysis/backtester.py`) — long-only hold 1 día, coste 0.05%/lado, equity curve, buy&hold, drawdown, Sharpe anualizado, CAGR, win rate, profit factor, alpha. Reutiliza predicciones OOS del CV sin reentrenar.
- [x] Pestaña "Backtest OOS" en UI (`backtest_widget.py`) — matplotlib con equity vs B&H arriba + drawdown abajo + panel de 9 métricas con colores. Se actualiza al terminar análisis y al clicar fila en la tabla.

### Fase 3 — Mejorar el modelo ✅ COMPLETADA

- [x] **ALG 1**: Target configurable mediante spinbox "Umbral ret." en toolbar — en Fase 5 evolucionó a regresión completa (el umbral ahora es threshold de inferencia, no de entrenamiento).
- [x] **ALG 3**: Features de calendario: `days_to_earnings`, `is_earnings_week`, `days_to_exdiv`, `is_pre_exdiv` via `yfinance` earnings dates + dividends. Vectorizadas con `numpy.searchsorted`. Default 90/0 si sin datos → nunca se pierden filas.
- [x] **ALG 4**: Kelly fraccionado (25%) implementado en `order_executor._kelly_size()` — requiere ≥20 trades OOS; usa win_rate, avg_win, avg_loss del backtest. Floor en 10% del monto para no sub-operar.

### Fase 4 — Optimización operativa ✅ COMPLETADA

- [x] **ALG 5 / Task 15**: Caché de modelo — `model_trainer.py` guarda `_meta.joblib` con `trained_date`, `n_features`, OOS indices/probs y métricas. `try_load_cache(symbol, n_features)` carga modelo + scaler del disco si fue entrenado hoy y el número de features coincide. Evita reentrenar 10–30s por símbolo en análisis repetidos. `trading_bot.py` incluye la rama cache-check antes de llamar a `train()`.
- [x] **DIS 2 / Task 16**: Log de órdenes en `PROJECT_ROOT/orders_log.csv` — `main_window._log_order_csv()` hace append tras cada orden buy/sell exitosa con 11 campos: `timestamp, symbol, action, qty, limit_price, amount, order_id, signal, prob_up, cv_accuracy, kelly_used`. Header automático si el archivo no existe.
- [x] **DIS 3 / Task 17**: Sorting activado al terminar el análisis — `setSortingEnabled(False)` durante el análisis para no romper índices de fila; `setSortingEnabled(True)` en `_on_all_done()`. Nuevo helper `_find_symbol_row(symbol)` itera columna 0 para encontrar la fila por texto (robusto con filas reordenadas). `_on_table_row_clicked` lee el símbolo desde `table.item(row,0).text()`.
- [x] **DIS 1 / Task 18**: Selector de período en gráfico — `chart_widget.py` añade QComboBox "3M/6M/1A/2A/Todo" sobre el canvas. `_df_full` almacena el DataFrame completo; `_render(df, symbol)` corta a los N últimos días según selección. Cambiar el combo redibuja instantáneamente sin recargar datos de disco. El título del gráfico muestra el período activo.

### Fase 5 — Edge del modelo ✅ COMPLETADA

- [x] **Sentimiento de noticias**: `data_loader.load_news(symbol)` — descarga `ticker.news` de yfinance, filtra últimas 72h, analiza cada titular con VADER (`vaderSentiment 3.3.2`). Devuelve `{sentiment_score: float[-1,1], sentiment_volume: int}`. Maneja formato plano y anidado de yfinance. UI: etiqueta "Sentimiento: positivo/negativo/neutro" con color verde/rojo.
- [x] **Put/call ratio**: `data_loader.load_options(symbol)` — `ticker.option_chain(expirations[0])`, suma `openInterest` de puts y calls, devuelve `{pc_ratio: float}` clampado [0.1, 10]. Default 1.0 si sin datos. UI: etiqueta "Put/Call ratio: X.XX (presión bajista/alcista/neutral)" con color.
- [x] **Regresión de retorno**: `feature_engineer.prepare_raw()` — target pasa de `(ret > threshold).astype(int)` a `ret.astype(float32)`. Eliminado `return_threshold` del entrenamiento. El spinbox UI ahora controla el threshold de inferencia (mínimo retorno predicho para COMPRAR).
- [x] **Ensemble XGBoost + LightGBM**: `model_trainer.py` reescrito — `XGBRegressor + LGBMRegressor` por fold (scaler independiente), predicciones promediadas; modelo final: ambos fit en todos los datos; métricas: `oos_ic` (Pearson), `oos_dir_acc`, `oos_mae`; feature importance = promedio de ambos; caché con `model_type="ensemble_regressor_v1"` invalida caches anteriores automáticamente.
- [x] **Ajuste de UI**: tabla col "Ret. Esperado" (±% coloreado); panel señal muestra `pred_return` en verde/rojo; métricas muestran IC/DirAcc/MAE; `OrderWorker` y `execute_signal()` usan `pred_return`; filtro de calidad cambia a `oos_dir_acc ≥ 52%`; CSV log usa `pred_return` + `dir_acc`. Deps añadidas al venv: `lightgbm 4.7.0`, `vaderSentiment 3.3.2`.

### Fase 6 — Scanner de mercado ✅ COMPLETADA

- [x] **Lista S&P100**: nuevo `src/data/sp100.py` — constante `SP100_SYMBOLS` con 100 tickers organizados por sector (tech, comunicaciones, consumo, salud, financiero, energía, industrial, utilities, real estate).
- [x] **Botón "Escanear S&P100"**: en toolbar junto a "Entrenar y Analizar" — color lila (#7733cc), tooltip con tiempo estimado; `_run_scan()` llama `_run_analysis(symbols=SP100_SYMBOLS, scan_mode=True)`. Ambos botones se deshabilitan durante análisis.
- [x] **Modo escaneo**: `_run_analysis(symbols, scan_mode)` — flag `self._scan_mode`; limpia `setRowHidden` del escaneo anterior antes de cargar; muestra mensaje de progreso con nº de símbolos.
- [x] **Filtro automático**: `_filter_scan_results()` — usa `table.setRowHidden(row, True)` en filas sin señal fuerte (signal in "COMPRAR"/"VENDER" AND `oos_dir_acc ≥ 0.52`); devuelve contador de señales; status bar muestra "X señales fuertes de Y analizados".
- [x] **Export scan_log.csv**: `_export_scan_log()` — append a `PROJECT_ROOT/scan_log.csv` solo con filas de señal fuerte; campos: `timestamp, symbol, signal, pred_return_pct, dir_acc_pct, ask, bid, sentiment_score, pc_ratio`; header automático.

### Fase 7 — Dashboard de portfolio ✅ COMPLETADA

- [x] **`order_executor.get_all_positions()`**: llama `api.list_positions()`, devuelve lista de dicts con symbol, side, qty, avg_entry_price, current_price, market_value, unrealized_pl, unrealized_plpc.
- [x] **`data_loader.load_intraday(symbol, days=5)`**: `api.get_bars(symbol, "1Hour", start, end).df` vía Alpaca; columnas a minúscula; timezone UTC; raise ValueError si sin datos.
- [x] **`src/ui/portfolio_widget.py`** (nuevo): dark theme consistente con el resto de la app. Layout: header (título + last-update label + botón Actualizar) → resumen cuenta (portfolio_value, buying_power, cash) → QSplitter(H): izquierda=posiciones+equity_curve / derecha=historial_alertas. `refresh()` llama los 4 loaders. `set_executor()` para inyección tardía de credenciales.
- [x] **Tabla posiciones**: 7 columnas (Símbolo, Lado, Qty, Entrada, Actual, P&L $, P&L %) con colores verde/rojo según P&L; mensaje "Sin posiciones" si vacío.
- [x] **Equity curve P&L**: lee `orders_log.csv`, calcula cash_flow (buy=negativo, sell=positivo), dibuja `cumsum` con fill coloreado; título muestra P&L neto total. Matplotlib oscuro.
- [x] **Historial alertas**: lee `scan_log.csv`, muestra las últimas 200 filas invertidas (más recientes arriba), coloreadas por señal (COMPRAR=verde, VENDER=rojo). Mensaje si sin archivo.
- [x] **`main_window.py`**: tercera pestaña "Portfolio" añadida al `QTabWidget`; `_on_tab_changed()` refresca automáticamente el portfolio al activar la pestaña; `PortfolioWidget(executor, PROJECT_ROOT)` inicializado con credenciales.
- [x] **Toggle Diario/1H en gráfico**: `chart_widget.py` añade combo "Intervalo: Diario / 1H (5d)" junto al selector de período; emite `timeframe_requested(symbol, tf)`; deshabilita selector de período en modo 1H. `main_window._on_chart_timeframe_requested()` carga `load_intraday()` para 1H o restaura df diario. `update_chart(reset_tf=True)` resetea toggle al cambiar símbolo.

### Fase 8 — Mejoras producción ✅ COMPLETADA (2026-08-12)

- [x] **scan_log.csv ampliado**: exporta TODAS las señales no-NEUTRAL (eliminado umbral `dir_acc ≥ 0.52`); UI scanner muestra también señales débiles.
- [x] **Alertas Telegram**: `src/notifications/telegram_notifier.py` — `send_alert(token, chat_id, text_html)` vía Bot API. Integrado en `main_window._send_telegram_scan_alert()` y en el scanner headless `scan_sp100.py`.
- [x] **Scanner headless**: `scan_sp100.py` — ejecución sin GUI para Task Scheduler; `scan_log_console.txt` como log persistente.
- [x] **run_scan.bat**: script de lanzamiento para Windows Task Scheduler; `cd /d %~dp0` + llamada a `.venv\Scripts\python.exe scan_sp100.py`.
- [x] **29 features** (antes 25): añadidas `vix`, `vix_chg_5d`, `rel_ret_5d`, `rel_ret_20d`. `data_loader.load_market()` carga VIX+SPY para contexto de mercado. Cache de modelo invalidado automáticamente (`model_type="ensemble_regressor_v2"`).

### Fase 9 — Puesta en producción ✅ COMPLETADA (2026-08-14)

- [x] **Task Scheduler configurado**: tarea `AlgoTrader_ScanSP100` creada en Windows Task Scheduler — Lun-Vie a las 14:45 local (= 09:45 ET, 15 min después de apertura), `StartWhenAvailable=True`, `RunOnlyIfNetworkAvailable`, timeout 2h. Comando: `C:\proyectos\AlgoTrader\run_scan.bat`.
- [x] **Tab Portfolio verificado**: código revisado — todos los estados sin datos manejados correctamente: sin executor (pasa silencioso), sin posiciones ("Sin posiciones abiertas"), sin `orders_log.csv` ("Sin órdenes registradas aún"), sin `scan_log.csv` (mensaje apropiado). Fix aplicado: `pd.read_csv(log_path, encoding="utf-8")` en `_load_scan_history()`.
- [x] **Evaluación impacto VIX+rel_ret**: scan completo S&P100 (48 señales no-NEUTRAL, 2026-08-12) con 29 features. Dir Acc media = **50.04%** (rango 48.0%–52.3%). Las 4 nuevas features de contexto macro NO mejoran Dir Acc de forma significativa — sigue siendo ~50%, lo cual es estructural al diseño de regresión (el modelo predice magnitud de retorno, no dirección). Solo 2 símbolos alcanzan Dir Acc ≥52% (ADI y MA) y ambos tienen señal débil, por lo que ninguna orden se ejecutaría. Conclusión: el edge del modelo está en la magnitud del retorno predicho (IC/MAE), no en la dirección binaria.

---

## DECISIONES DE DISEÑO A VALIDAR

Antes de implementar la Fase 2 y 3, hay decisiones que dependen del objetivo:

| Decisión | Opción A | Opción B |
|---|---|---|
| Target del modelo | Retorno > 0.5% (más señales, menos precisas) | Retorno > 1% (menos señales, más precisas) |
| Universo de activos | Cualquier ticker que el usuario ingrese | Lista curada de los 100 más líquidos (S&P100) |
| Timeframe | Diario (actual) | Diario + confirmación intraday (1h) |
| Backtest window | Walk-forward expanding | Walk-forward rolling (ventana fija de 3 años) |
