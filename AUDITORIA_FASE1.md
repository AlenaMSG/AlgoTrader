# AlgoTrader — Auditoría Fase 1 (solo lectura)

> Fecha: 2026-09-28. Repositorio leído completo: 30 módulos Python, `MEJORAS.md` (historial de 9 fases previas), `settings.json`, `models/` (1496 ficheros), `data_cache/`.
> **No se ha modificado ningún archivo de código en esta fase.**

---

## 1. ARQUITECTURA ACTUAL

### Flujo de datos por símbolo (`TradingBot.run_symbol`, `src/analysis/trading_bot.py`)

```
DataLoader.load(symbol)                 → OHLCV diario (fuente según settings.json)
DataLoader.load_calendar(symbol)        → earnings + ex-dividend dates (yfinance)
DataLoader.load_news(symbol)            → sentimiento (Alpha Vantage o VADER/yfinance)
DataLoader.load_options(symbol)         → put/call ratio (yfinance)
DataLoader.load_market()                → VIX + SPY (contexto macro)
        ↓
FeatureEngineer.prepare_raw()           → 29 features + target (retorno t+1)
        ↓
ModelTrainer.train()                    → TimeSeriesSplit(5) + modelo final sobre TODO el histórico
        ↓
ModelTrainer.predict(última barra)      → señal COMPRAR/VENDER/NEUTRAL + retorno predicho
        ↓
Backtester.run(predicciones OOS de CV)  → equity curve, Sharpe, drawdown, win rate...
        ↓
OrderExecutor.execute_signal()          → filtro Dir.Acc ≥ 50% → Kelly sizing → orden límite Alpaca paper
```

**Dónde se decide comprar/vender:**
- La señal nace en `ModelTrainer.predict()` (`src/analysis/model_trainer.py:278-299`): compara el retorno predicho contra un umbral fijo (±0.5%).
- La decisión de ejecutar o no nace en `OrderExecutor.execute_signal()` (`src/trading/order_executor.py:191`): primer filtro es `oos_dir_acc >= MIN_DIR_ACCURACY` (actualmente **0.50**).
- El tamaño de la posición sale de `_kelly_size()` (línea 162), que usa `win_rate`/`avg_win`/`avg_loss` del mismo backtest que se audita más abajo por look-ahead.

### Dos frentes de ejecución en producción
1. **Automático**: `scan_sp100.py` vía Task Scheduler (Lun-Vie 14:45 hora local = 09:45 ET), escanea los 100 símbolos, escribe `scan_log.csv` y `pending_signals.json`, envía alerta Telegram.
2. **Manual**: UI de escritorio (PyQt6) o dashboard web (Dash) permiten analizar un símbolo y ejecutar la orden con un clic (`web/pages/analisis.py`, `main_window.py`).

Ambos frentes comparten el mismo `TradingBot`/`ModelTrainer`/`OrderExecutor` — no hay una ruta de código separada para "solo simular" vs "operar de verdad" más allá del `base_url` (paper vs live) de Alpaca.

### Modelos: 1 por símbolo, no 1 global
`models/` contiene actualmente **1496 ficheros** para ~100 símbolos: cada símbolo tiene su propio modelo entrenado de forma independiente (más restos de `model_type` antiguos como `AAPL_lgb.joblib`, `AAPL_random_forest_*` conviviendo con el ensemble — nunca se limpian los modelos de tipos descartados). Esto multiplica por 100 el riesgo de overfitting: cada modelo ve, como mucho, ~15 años de barras diarias (~3.800 filas) y entrena 500 árboles (XGB) + 500 árboles (LGBM) sobre eso.

---

## 2. FUENTES DE DATOS

| Fuente | Ajustada por splits/dividendos | Estado real en el código |
|---|---|---|
| **Yahoo Finance** (`load_yfinance`) | ✅ Sí (`auto_adjust=True`) | Es la única fuente correctamente ajustada. Es también la que el propio prompt del usuario descarta para producción (rate limits, sin SLA, términos de uso ambiguos para uso comercial). |
| **Alpaca** (`load_alpaca_bars`) | ❌ **NO** — `adjustment="raw"` explícito (`data_loader.py:340`) | 🔴 **Es la fuente ACTIVA ahora mismo** (`settings.json: "data_source": "alpaca"`). Ver bug crítico #1 abajo. |
| **Alpha Vantage** (`load_alpha_vantage`) | ✅ Sí (`adjusted close`) | Correcta, pero plan gratuito = 25 llamadas/día, inservible para escanear 100 símbolos. |
| **Polygon.io** (`load_polygon`) | ✅ Sí (`adjusted: true`) | Correcta, requiere plan de pago, nunca se ha usado en producción (no hay `POLYGON_API_KEY`). |

**Ninguna fuente incluye empresas deslistadas** — ver sección 3 (survivorship bias).

**Frecuencia**: diaria (`interval="1d"`). Hay soporte para 1h vía Alpaca (`load_intraday`) pero solo se usa en el visor de gráficos, no en el pipeline de señales.

**Calidad**: caché en disco de 20h — razonable para datos diarios. Sin embargo, la caché de Yahoo y Alpaca conviven en `data_cache/` bajo nombres distintos (`AAPL_daily.parquet` vs `AAPL_alpaca_daily.parquet`) y **no se invalidan al cambiar `data_source` en `settings.json`** — si un usuario cambia de fuente, sigue viendo la caché de la fuente anterior hasta que expira, lo que puede ocultar el bug de ajuste durante horas.

---

## 3. ERRORES DE METODOLOGÍA

### 🔴 CRÍTICO — Precios sin ajustar activos en producción ahora mismo
`settings.json` tiene `"data_source": "alpaca"`, y `load_alpaca_bars()` pide barras con `adjustment="raw"` (`src/data/data_loader.py:340`). Esto significa que **todo el histórico de precios que alimenta los 100 modelos en producción contiene saltos artificiales en cada split** (p. ej. NVDA hizo un split 10:1 en 2024; AAPL ha tenido varios en su historia). Un split no ajustado se ve como una caída del ~90% de un día para otro — el modelo lo interpreta como una señal de mercado real, contamina `log_ret_*`, `sma_ratio`, `atr`, `bb_*`, literalmente cada feature basado en precio. Esto invalida cualquier modelo entrenado con esta configuración, no es una hipótesis, es un hecho verificable en el código.

### 🔴 CRÍTICO — Look-ahead / fill no ejecutable en el backtest
`Backtester._simulate()` (`src/analysis/backtester.py:63-68`):
```python
for i in range(n - 1):
    if preds[i] >= self.buy_threshold:
        entry = closes[i]     * (1 + self.cost_pct)   # ← entra AL MISMO cierre que generó la señal
        exit_ = closes[i + 1] * (1 - self.cost_pct)
```
`preds[i]` es la predicción calculada con features que **requieren el cierre del día i** (`log_ret_1d`, `rsi`, etc. todos usan `close[i]`). Por tanto la señal solo se conoce *después* de que `close[i]` ya es un hecho consumado — pero el backtest simula comprar exactamente a ese mismo precio, con coste de solo 0.05%. Eso no es ejecutable en la realidad: como muy pronto se podría comprar a la apertura del día i+1, no al cierre del día i. Esto **infla artificialmente** el rendimiento reportado (win rate, Sharpe, profit factor) y por tanto también infla el tamaño de posición Kelly, que usa esas mismas métricas.

Lo llamativo: `MEJORAS.md` (Fase 2, "ALG 2") ya identificó esto explícitamente — *"Entrar en cada señal COMPRAR/VENDER con el precio de apertura del día siguiente"* — y quedó marcado como "✅ COMPLETADA", pero el código actual **no lo implementa**. Es documentación desincronizada del código real: la razón por la que "los cambios anteriores no funcionaron" (ver sección 5) es en parte que el estado del proyecto documentado en `MEJORAS.md` no coincide con el estado real del código.

### 🔴 ALTO — Survivorship bias por diseño
`src/data/sp100.py` es una lista estática de los 100 componentes **actuales** del S&P 100 (2025). Cualquier empresa que fue excluida del índice, se fusionó, quebró o fue adquirida entre 2010 y hoy simplemente no aparece. El backtest solo puede "ver" ganadores supervivientes — sesga el rendimiento reportado sistemáticamente al alza, especialmente en periodos largos (2010-2026 incluye la salida de GE del Dow, quiebras/adquisiciones del sector energético 2015-16, etc., ninguna capturada).

### 🟠 ALTO — Filtro de calidad rebajado a nivel de azar (causa raíz del bucle, ver sección 5)
`MIN_DIR_ACCURACY = 0.50` en `src/trading/order_executor.py:15`, con el propio comentario del autor: *"umbral reducido — 52% era estructuralmente imposible con regresión"*. En un problema de predicción de dirección binaria, 50% de accuracy es exactamente lo que se espera si el modelo no tiene ninguna información — es el filtro que se suponía debía impedir operar sin ventaja estadística, y ahora no filtra nada.

### 🟠 ALTO — Feature no estacionaria: precio absoluto como input del modelo
`FEATURE_COLS` incluye `"close"` (precio de cierre en dólares, sin normalizar) en `feature_engineer.py:29`. Entrenar un árbol de decisión con el precio absoluto como feature le permite "memorizar" la tendencia temporal general (si AAPL subió de $10 a $250 en el periodo de entrenamiento, el modelo puede aprender reglas del tipo "si close > $150, es probable que sea 2023+" en vez de relaciones genuinas entre indicadores y retorno futuro). Esto es una forma sutil de overfitting temporal — funciona bien in-sample y se rompe en cuanto el precio sale del rango visto en entrenamiento.

### 🟠 MEDIO — Validación de "mejoras" sin metodología fija (no exactamente look-ahead, pero es la causa directa del bucle)
`backtest_semana.py` es el único script que compara predicción vs realidad fuera del CV interno, y:
- Las fechas (`CUTOFF`, `REAL_DESDE`, `REAL_HASTA`) están hardcodeadas y se reescriben manualmente cada vez que se ejecuta — no hay una ventana fija reutilizable.
- N=15 símbolos, 1 semana → estadísticamente no puede distinguir señal de ruido (con 15 muestras binarias, el intervalo de confianza al 95% para una proporción observada de 53% cubre aproximadamente 30%-76%).
- No fija semilla aleatoria en ningún sitio del pipeline (XGBoost/LightGBM/RandomForest sí tienen `random_state=42` fijo en los hiperparámetros, eso está bien — pero el *periodo* de validación cambia cada vez, así que no es comparable ejecución a ejecución).
- No se guarda el resultado de ninguna ejecución anterior para comparar — cada vez que se corre, se pierde el resultado previo.

Esto es la causa mecánica de por qué "los cambios anteriores no funcionaron": literalmente no hay forma de saber, mirando el histórico de `MEJORAS.md`, si la Fase 5 mejoró o empeoró el sistema respecto a la Fase 4, porque cada fase se "validó" contra una ventana temporal distinta y no reproducible.

### 🟡 MEDIO — Costes modelados de forma incompleta
El coste de 0.05% por lado (`cost_pct=0.0005`) sí está presente y coincide con lo que pide el usuario como mínimo. Pero:
- No hay slippage adicional dependiente de volumen/liquidez (una orden de $1000 en una acción de bajo volumen mueve el precio más que 0.05%).
- No se modela el spread bid-ask real — el precio de entrada usado es `close`, no `ask` (en compra) ni `bid` (en venta), que es lo que `OrderExecutor` sí usa correctamente en producción (`quote["bid_price"] + 0.01` / `quote["ask_price"] - 0.01`). El backtest y la ejecución real usan modelos de precio distintos.

### 🟡 MEDIO — Fuga de información sutil entre features y calendario
`_days_to_next` en `feature_engineer.py:180-205` calcula "días hasta el próximo earnings/ex-dividend" usando `ticker.get_earnings_dates(limit=40)` y `ticker.dividends`, ambos descargados **hoy** (fecha de ejecución del script), no como estaban disponibles en el momento histórico `t` de cada fila de entrenamiento. yfinance no expone fácilmente el calendario "tal y como se conocía en 2015", así que esto asume que las fechas de earnings/dividendos futuras (relativas a cada fila histórica) eran perfectamente conocidas con antelación en ese momento — en la práctica las fechas de earnings se confirman con semanas de antelación, así que el efecto es pequeño pero existe, y es sistemáticamente optimista.

### 🟡 BAJO — Sin backtest a nivel de cartera
Cada símbolo se backtestea de forma aislada. No existe ninguna simulación conjunta de "qué pasaría si opero los 100 símbolos con capital compartido, límites de exposición y correlación entre posiciones" — el Kelly fraccionado se calcula por símbolo sin conocer cuánto capital ya está comprometido en otras posiciones simultáneas del mismo sector.

---

## 4. BUGS DE CÓDIGO Y LÓGICA DE SEÑALES

| # | Bug | Archivo:línea | Impacto |
|---|---|---|---|
| 1 | `adjustment="raw"` en Alpaca, fuente activa en `settings.json` | `data_loader.py:340` | 🔴 Crítico — ver sección 3 |
| 2 | Backtest entra al mismo cierre que genera la señal (no ejecutable) | `backtester.py:63-68` | 🔴 Crítico — ver sección 3 |
| 3 | `MIN_DIR_ACCURACY` rebajado a nivel de azar | `order_executor.py:15-16` | 🔴 Alto |
| 4 | Caché de datos no se invalida al cambiar `data_source` | `data_loader.py` (archivo de caché distinto por fuente, sin limpieza cruzada) | 🟠 Medio — puede ocultar bugs de fuente durante horas |
| 5 | `models/` acumula ficheros de `model_type` obsoletos sin limpiar (1496 ficheros para ~100 símbolos) | `model_trainer.py` (`_path_a/_path_b/_meta_path` incluyen `model_type` en el nombre, nunca se purgan los antiguos) | 🟡 Bajo — solo espacio en disco y confusión, pero ilustra la falta de disciplina de limpieza del bucle |
| 6 | `requirements.txt` desactualizado — faltan `xgboost`, `lightgbm`, `vaderSentiment`, `alpha_vantage`, `openpyxl`, `dash`/`dash-bootstrap-components`, `python-dotenv` | `requirements.txt` | 🟡 Bajo — un `pip install -r requirements.txt` en una máquina nueva no reproduce el entorno real |
| 7 | Cero tests unitarios en todo el repositorio (`find` no encontró ningún `test_*.py`) | — | 🟠 Medio — imposible validar que un refactor del cálculo de señales o del backtest no rompe nada, condición explícita de la Fase 4 del usuario |
| 8 | `backtest_semana.py` no pasa `calendar`/`market` a `FeatureEngineer.prepare_raw()` (`fe.prepare_raw(df_cut)`), a diferencia del pipeline de producción que sí los pasa | `backtest_semana.py:96` | 🟡 Bajo — el "backtest" ad-hoc ni siquiera usa las mismas 29 features que producción, por lo que no es comparable |

---

## 5. CAUSA RAÍZ DEL BUCLE

Tres factores se combinan, y ninguno es un bug aislado — son la misma decisión estructural repetida de tres formas distintas:

1. **No existe un backtest reproducible fijo** (mismos datos, mismo periodo, misma semilla) contra el que medir cada cambio. `backtest_semana.py` cambia de ventana temporal cada vez que se ejecuta, y el backtest "oficial" (`Backtester` + CV de `ModelTrainer`) tiene un bug de ejecución no realista (punto 2 de la sección 4) que infla los resultados de forma que "parece que funciona" en cada fase, aunque el filtro de accuracy direccional en producción siga fallando.

2. **Cuando el criterio de aceptación falla, se ha rebajado el criterio en vez del modelo.** `MIN_DIR_ACCURACY` pasando de 52% a 50% con un comentario que literalmente dice que 52% "era estructuralmente imposible" es la prueba directa: en vez de aceptar que la evidencia (Fase 9 de `MEJORAS.md`: Dir Acc = 50.04% media tras seis fases de mejoras) decía "este enfoque no tiene ventaja con estos datos y este target", se ajustó el umbral para que el sistema siguiera generando operaciones.

3. **Se sigue añadiendo complejidad (features, ensembles, fuentes de datos) sin descartar nunca una hipótesis fallida.** `MEJORAS.md` documenta 9 fases, todas marcadas "✅ COMPLETADA", ninguna marcada "descartada". La propia Fase 9 concluye explícitamente que las 4 features de contexto macro no mejoraron nada — pero esas features **no se revirtieron**, siguen en el modelo activo. No hay ningún mecanismo en el proyecto (hasta este `DECISIONS.md`) que obligue a comparar "antes vs después" con el mismo backtest y descartar lo que no funciona.

En resumen: el sistema no está atascado por falta de ideas, está atascado porque nunca hubo una vara de medir fija, y cada vez que la vara indicaba "esto no funciona", se cambió la vara.

---

## 6. LISTA PRIORIZADA

### Impacto alto (bloquean cualquier conclusión fiable)
1. Fuente de datos activa (`alpaca`, `adjustment="raw"`) corrompe todos los precios históricos en producción.
2. Backtest con fill no ejecutable (entra al cierre que genera la señal) infla todas las métricas de rendimiento y el sizing Kelly derivado de ellas.
3. `MIN_DIR_ACCURACY` en 50% no filtra nada — el sistema puede estar operando sin ninguna ventaja estadística ahora mismo.
4. No hay backtest reproducible fijo (mismos datos/periodo/seed) — sin esto, la Fase 3 (probar estrategias) repetirá el mismo bucle.
5. Survivorship bias: universo limitado a supervivientes actuales del S&P100.

### Impacto medio
6. Feature `close` no estacionaria como input directo del modelo.
7. Costes de ejecución incompletos (sin slippage por liquidez, sin modelar spread real en el backtest).
8. Cero tests unitarios — cualquier cambio en Fase 3/4 no tiene red de seguridad.
9. Caché de datos no se invalida entre fuentes — puede ocultar bugs durante horas.
10. Backtest ad-hoc (`backtest_semana.py`) usa features distintas a producción — no es comparable.

### Impacto bajo
11. `requirements.txt` desactualizado (entorno no reproducible desde cero).
12. Acumulación de modelos obsoletos en disco (1496 ficheros).
13. Días hasta earnings/dividendos calculados con calendario "de hoy" en vez de "como se conocía entonces" (sesgo pequeño, sistemáticamente optimista).

---

## Próximo paso propuesto

Con esta auditoría aprobada, la Fase 2 (base sólida) debería, en este orden:
1. Corregir el bug de fuente de datos (o forzar `data_source=yahoo`/Polygon ajustado como único modo válido hasta resolver la evaluación de fuentes).
2. Arreglar el fill del backtest (entrada a la apertura de t+1, no al cierre de t).
3. Construir el backtest walk-forward de cartera completa con holdout out-of-sample reservado, y **congelarlo** como la única vara de medir — cualquier cambio posterior se compara contra este mismo backtest, mismos datos, mismo periodo, misma semilla.
4. Restaurar `MIN_DIR_ACCURACY` (o el criterio equivalente en un enfoque de regresión) a un nivel que refleje ventaja estadística real, no el nivel más bajo que permite seguir operando.

No se toca nada de esto hasta que el usuario apruebe esta Fase 1.
