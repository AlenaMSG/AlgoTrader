# DECISIONS.md — Registro de hipótesis, cambios y resultados

> Regla: máximo 3 intentos por hipótesis. Si no mejora tras el backtest reproducible
> (mismo seed, mismos datos, mismo periodo), se descarta y se documenta por qué.
> Antes de proponer nada nuevo, revisa esta tabla — si ya se probó, no lo repitas.

## Formato de cada entrada

```
### [FECHA] Hipótesis: <qué se prueba y por qué debería funcionar>
- Intento: 1/3
- Cambio: <qué se modificó exactamente — commit/archivo>
- Validación: <backtest usado, periodo, seed>
- Resultado: <métrica antes vs después>
- Conclusión: ACEPTAR / DESCARTAR / REPETIR
- Por qué: <razón>
```

---

## Hipótesis ya probadas ANTES de este proceso (extraídas de MEJORAS.md — no repetir)

### [2026-08-12] Hipótesis: añadir contexto macro (VIX, retorno relativo vs SPY) mejora la accuracy direccional
- Intento: 1/3 (histórico, previo a este proceso)
- Cambio: Fase 8 de MEJORAS.md — añadidas 4 features (`vix`, `vix_chg_5d`, `rel_ret_5d`, `rel_ret_20d`), 25→29 features
- Validación: scan completo S&P100, 48 señales no-NEUTRAL, un único día (2026-08-12), sin holdout temporal, sin control de significancia estadística
- Resultado: Dir Acc media 50.04% (rango 48.0%–52.3%). Solo 2/48 símbolos ≥52%, ambos con señal débil (ninguna orden se habría ejecutado)
- Conclusión: **DESCARTAR** (documentado como tal en MEJORAS.md Fase 9, pero las features NO se revirtieron — siguen en producción)
- Por qué: sin edge medible; el ruido de 48 muestras de un solo día no permite distinguir señal de azar. **Nota metodológica**: esta validación no cumple los requisitos de la Fase 2 (walk-forward, holdout, múltiples periodos) — es el patrón exacto que hay que dejar de usar.

### [reiterado] Hipótesis: bajar el umbral de accuracy direccional mínima permite operar más
- Cambio: `order_executor.py:15` — `MIN_DIR_ACCURACY` bajado de 0.52 a 0.50, con comentario explícito en el código: *"umbral reducido — 52% era estructuralmente imposible con regresión"*
- Resultado: el filtro que debía garantizar ventaja estadística ahora acepta el equivalente a una moneda al aire (50% = azar puro en un problema binario de dirección)
- Conclusión: **DESCARTAR — es la causa raíz del bucle, no una mejora.** Ver informe de auditoría Fase 1, sección "Causa raíz".
- Por qué: en vez de aceptar que el modelo no tenía poder predictivo y cambiar de enfoque, se relajó el criterio de aceptación para forzar que siguiera operando.

### [ongoing] Hipótesis: sumar features informativos (sentimiento VADER, put/call ratio, calendario earnings/dividendos, ensemble XGB+LGB) mejora el poder predictivo
- Cambio: Fases 5–8 de MEJORAS.md, seis meses de iteración
- Validación: nunca con walk-forward out-of-sample reservado ni benchmark buy&hold formal a nivel de cartera; solo `backtest_semana.py` (script ad-hoc, N=15 símbolos, 1 semana, fechas hardcodeadas que cambian cada vez que se ejecuta, sin seed fijo, sin comparación con una ejecución anterior guardada)
- Resultado: sin evidencia registrada de mejora acumulada; `MIN_DIR_ACCURACY` tuvo que bajarse para que el sistema operara
- Conclusión: **DESCARTAR el método de validación en sí** — no genera conocimiento acumulable porque cada ejecución compara contra una ventana distinta sin un baseline fijo. No se puede saber si 6 meses de cambios mejoraron o empeoraron nada.
- Por qué: no hay un backtest reproducible (mismos datos, mismo periodo, misma semilla) contra el que medir cada cambio. Esta es la Fase 2 pendiente.

---

## Nuevas hipótesis (a partir de ahora)

_(se registrará aquí cada hipótesis de la Fase 3 en adelante, tras aprobación del usuario)_

### Fuentes evaluadas el 2026-10-14 (Alpha Vantage, plan gratuito, y trading-agents.ai)

Restricciones verificadas con la clave gratuita: **25 peticiones/día, 1 petición/segundo**. Solo sirve para datos que se descargan una vez y se cachean, nunca para peticiones por símbolo dentro del scan S&P100.

Probado y **PREMIUM** (no usable con clave gratuita):
- `TIME_SERIES_DAILY_ADJUSTED` → `DataLoader.load_alpha_vantage()` (`src/data/data_loader.py:391`) no funciona con la clave actual. Alpha Vantage **no** es alternativa gratuita para precios ajustados.
- `NEWS_SENTIMENT` → `load_news()` cae al fallback VADER sin romper (`data_loader.py:206`), pero gasta una petición inútil por símbolo.
- También premium: intradía, opciones, insider transactions, earnings transcripts, OVERVIEW / estados financieros.

### [2026-10-14] Hipótesis: el universo sin empresas deslistadas infla los resultados del backtest (sesgo de supervivencia)
- Estado: **BLOQUEADA (2026-10-14) — faltan datos, no se descarta**
- Intento: 0/3
- Comprobación hecha: precios desde 2016 de 7 ex-miembros del S&P100 deslistados (CELG, MON, TWX, RTN, TWTR, ATVI, ALXN):
  - Yahoo: **ninguno** devuelve datos.
  - Alpaca IEX: solo 4, y solo desde 2020-07-27. "MON" devuelve 2021-03→2022-12 cuando Monsanto se deslistó en 2018 → **ticker reutilizado por otra empresa**: usar Alpaca sin mapeo de identificadores metería datos falsos.
  - `LISTING_STATUS` da quién se deslistó, pero no la **pertenencia histórica al S&P100**.
- Qué falta para desbloquear: una fuente con precios de deslistadas + composición histórica del índice (p. ej. Norgate Data, CRSP, Sharadar/Nasdaq Data Link; todas de pago). Sin eso, el backtest fijo usa los 100 supervivientes actuales y **sus resultados están sesgados al alza**: si aun así no hay ventaja, la conclusión es todavía más firme.
- Cambio propuesto: usar `LISTING_STATUS&state=delisted&date=AAAA-MM-DD` (gratuito, verificado: devuelve CSV con `delistingDate`) para incluir en el backtest walk-forward los símbolos que cotizaban en la fecha de inicio y se deslistaron después. Cachear el CSV en disco.
- Limitación conocida: da estado de cotización, **no** pertenencia histórica al S&P100. Reduce el sesgo pero no lo elimina.
- Validación: comparar métricas del backtest de cartera con universo actual vs universo point-in-time, mismo periodo y misma semilla.
- Resultado: —
- Conclusión: —

### [2026-10-14] Hipótesis: los splits de `SPLITS` permiten verificar que los precios usados están bien ajustados (bug crítico nº1 de la auditoría)
- Estado: **HECHO (2026-10-14)**
- Intento: 1/3
- Cambio:
  - `src/data/data_loader.py` `load_alpaca_bars()`: `adjustment="raw"` → `"all"`; caché renombrada a `{SYM}_alpaca_adj_daily.parquet` para no reutilizar la caché raw antigua.
  - `src/analysis/model_trainer.py`: `DATA_VERSION = 2` guardado en el meta del modelo; `try_load_cache()` descarta modelos con otra versión (los 100 modelos `random_forest` entrenados el 2026-10-14 con precios raw ya no se reutilizan).
  - `tests/test_split_adjustment.py` + `tests/fixtures/splits_av.json` (10 splits de 8 símbolos desde 2020-07-27, de AV `SPLITS`).
- Validación: con `adjustment="raw"` el detector marca los 10 splits (NVDA 2024-06-10 ratio 0.101, AMZN 2022-06-06 0.051…); con el arreglo, Alpaca y Yahoo pasan los 3 tests.
- Resultado: precios ajustados en las dos fuentes usables gratis.
- Conclusión: **ACEPTAR**
- Notas: el feed IEX gratuito de Alpaca solo tiene histórico desde **2020-07-27** (~6 años, no 2010). Las cachés `*_alpaca_daily.parquet` antiguas y los modelos raw siguen en disco (no se pudieron borrar desde la sesión); ya no se usan, se pueden borrar a mano.

### [2026-10-14] Fase 2 paso 2: backtest con fill ejecutable (bug nº2 de la auditoría)
- Estado: **HECHO**
- Cambio: `src/analysis/backtester.py` — la señal de t (que usa `close[t]`) entra a `open[t+1]` y sale a `open[t+2]`; las aperturas se buscan por fecha en la serie completa (`prices=df_raw`, pasado desde `trading_bot.py`). Sharpe calculado sobre todos los días, no solo los días con operación (también lo inflaba). Tests: `tests/test_backtester.py` (3, sin red).
- Validación: con los mismos precios sintéticos, la versión antigua daba +1% por operación y la nueva, pérdidas (el gap de apertura se come el movimiento). Prueba end-to-end NVDA (Alpaca ajustado, random_forest, 2020-07→2026-10): Dir Acc OOS 48.9%, 204 operaciones, retorno **−15.9%** vs buy&hold **+1012.8%**, Sharpe 0.00.
- Conclusión: **ACEPTAR** (es un arreglo de medición, no una mejora de estrategia). El resultado honesto confirma la Fase 9 de MEJORAS.md: sin ventaja.

### [2026-10-14] Fase 2 paso 4: restaurar el filtro de capacidad predictiva
- Estado: **HECHO**
- Cambio: `src/trading/order_executor.py` — `MIN_DIR_ACCURACY` 0.50 → **0.52** (suelo) y nueva `min_dir_accuracy(n_samples)`: exige además que el 50% quede fuera del IC 95% con las ~5/6·n predicciones OOS del CV (1.500 filas → 52.8%; 4.000 → 51.7%, pero nunca menos de 52%). Test: `tests/test_order_filter.py`.
- Efecto esperado: con las métricas honestas la mayoría de símbolos no pasará el filtro (NVDA 48.9%) y el Kelly del backtest corregido saldrá negativo → muchas menos órdenes. **Es el comportamiento correcto**: no operar sin ventaja.
- Regla: este umbral no se vuelve a bajar para "conseguir operaciones".

### [2026-10-14] Fase 2 paso 3: criterio de aceptación PRE-REGISTRADO (escrito antes de ver resultados)
Vara de medir única: `backtest_fijo.py` (walk-forward, snapshot de datos congelado). Cualquier estrategia, modelo o filtro se **ACEPTA** solo si, en el periodo de desarrollo, cumple **las tres**:
1. Sharpe de la cartera > Sharpe del benchmark equiponderado del mismo universo (mismos costes de ejecución en apertura).
2. IC medio diario de sección cruzada (Spearman pred vs retorno real) > 0 con **t-stat > 2**.
3. Límite inferior del IC 95% del % de acierto de las señales de compra (retorno neto open→open > 0) **> 50%**.

Y después, **una sola ejecución** sobre el holdout congelado debe mantener (1) y (2) con signo correcto. Si falla el holdout, se descarta; no se vuelve a mirar el holdout con otra variante. Estos umbrales **no se relajan**: si nada los cumple, la conclusión es "no hay ventaja", no "bajar el umbral".

### [2026-10-14] Resultado del backtest fijo — modelo de producción (`random_forest`, 29 features)
- Snapshot `backtest_data/v1` (98 símbolos; TFC y MMC no disponibles en Yahoo), config_hash `9d766ec9deed`, resultado `backtest_results/20261014_174900_desarrollo_random_forest_base.json`
- Periodo desarrollo 2016-01-04 → 2025-09-30, 240.100 predicciones, 24.368 operaciones.

| | Estrategia | Benchmark equiponderado |
|---|---|---|
| Retorno total | **−16.0%** | **+403.3%** |
| CAGR | −1.8% | +18.1% |
| Sharpe | 0.02 | 1.07 |
| Max drawdown | −43.4% | −32.8% |

- Acierto compras 50.2% (IC95 49.6%–50.9%) · IC medio −0.003 (t = −0.76) · Dir Acc close→close 48.9%
- Por año: pierde contra el benchmark en 9 de 10 años (solo gana en 2023: +25.7% vs +21.9%).
- Criterios: 1 ❌ 2 ❌ 3 ❌ → **NO ACEPTADO**. El holdout **no se ejecuta** (solo se usa para confirmar algo aceptado en desarrollo; sigue sin tocar).
- Conclusión: **el modelo no tiene ninguna capacidad predictiva** medida de forma honesta (IC ≈ 0, acierto = moneda). Confirma la Fase 9 de MEJORAS.md, ahora con 240k predicciones en vez de 48. Y es un resultado **optimista** (sesgo de supervivencia, calendario de earnings con fuga).
- Implicación: añadir features, cambiar umbrales o filtros sobre estas señales no puede crear una ventaja que no existe. El siguiente paso tiene que ser un **enfoque distinto** (target, horizonte o tipo de estrategia), evaluado con este mismo backtest — decisión del usuario.

### [2026-10-14] PRE-REGISTRO — enfoques distintos (aprobado por el usuario: "prueba un enfoque distinto")
Parámetros fijados **antes** de ejecutar. Todos: long-only, universo y snapshot `v1`, señal con el cierre de t → entrada a `open[t+1]`, salida a `open[t+1+H]`, top 10 valores equiponderados, coste 0.05% por lado sobre la rotación real, mismo benchmark y **mismo criterio de aceptación (1, 2 y 3)**. El IC del criterio 2 se mide en las fechas de rebalanceo (no solapadas) contra el retorno open→open de H días.
- **E1 — Momentum 12-1** (no ML, anomalía documentada en la literatura): puntuación = retorno de t−252 a t−21; compra los 10 mayores; H = 21 días.
- **E2 — Reversión a corto plazo** (no ML): puntuación = −retorno de 5 días; compra los 10 que más han caído; H = 5 días.
- **E3 — ML con otro horizonte**: mismo `random_forest` y 29 features que producción, pero target = retorno a 20 días (no a 1 día) y purga de 20 días en el walk-forward; compra los 10 con mayor predicción; H = 20 días.
- Nota sobre el criterio 3: con posiciones de varias semanas en un mercado alcista es más fácil que el % de aciertos supere el 50%, así que el peso real lo llevan los criterios 1 y 2.
- Cada uno es el intento 1/3 de su hipótesis. El holdout solo se ejecuta para los que pasen en desarrollo.

#### Resultados (periodo de desarrollo; JSON en `backtest_results/`)
| | Retorno | Benchmark | Sharpe (bench) | Max DD | IC medio (t) | Acierto | Criterios 1/2/3 | Conclusión |
|---|---|---|---|---|---|---|---|---|
| **E1 momentum** (116 rebalanceos) | +600.3% | +396.9% | 0.95 (1.06) | −32.8% | 0.001 (t 0.05) | 57.8% | ❌ ❌ ✅ | **DESCARTAR** |
| **E2 reversión** (489 rebalanceos) | +268.5% | +401.8% | 0.66 (1.07) | −42.2% | 0.006 (t 0.53) | 53.3% | ❌ ❌ ✅ | **DESCARTAR** |
| **E3 ml20** (121 rebalanceos) | +752.7% | +425.5% | 1.08 (1.11) | −32.6% | 0.0006 (t 0.04) | 57.4% | ❌ ❌ ✅ | **DESCARTAR** |

- E1: más retorno total que el benchmark, pero con más volatilidad (Sharpe menor) y **IC ≈ 0**: la puntuación no ordena las acciones; el retorno extra viene de concentrarse en pocos ganadores (NVDA y similares), justo lo que el sesgo de supervivencia exagera. El criterio 3 pasa por la deriva alcista (ver nota del pre-registro), no por ventaja.
- E2: peor que el benchmark en todo.
- E3: el que más se acerca (Sharpe 1.08 vs 1.11, más retorno total), pero **IC = 0.0006 (t 0.04)**: las predicciones del modelo a 20 días no ordenan las acciones mejor que el azar. Igual que E1, el retorno extra sale de una cartera concentrada de 10 valores en un universo de supervivientes, no de capacidad predictiva.
- **Conclusión conjunta (4 enfoques, 2026-10-14)**: con datos diarios de precio del S&P100 actual, ni ML (1 y 20 días) ni reglas clásicas (momentum, reversión) muestran capacidad predictiva medible. El siguiente paso razonable es o bien otra fuente de información (no más transformaciones del mismo precio), o asumir que el objetivo realista es una cartera pasiva/sistemática barata.
- No se gastan intentos 2 y 3 variando parámetros (lookback, top N): con IC ≈ 0, ajustar parámetros sería buscar ruido.

### [2026-10-14] Hipótesis: no abrir posiciones N días antes de la publicación de resultados reduce el drawdown sin reducir el retorno ajustado al riesgo
- Estado: **DESCARTADA (2026-10-14)** sobre el modelo actual
- Intento: 1/3 — N=3 días fijado antes de ver el resultado (`backtest_fijo.py run --variant earnings_skip_3`)
- Resultado: Sharpe 0.016 → 0.019, max DD −43.4% → −43.1%, retorno −16.0% → −14.8%, 24.368 → 23.134 operaciones. Criterios 1/2/3 ❌.
- Por qué se descarta sin gastar los intentos 2 y 3: el cambio es ruido, y un filtro sobre señales sin ventaja no puede crearla. Solo tiene sentido reabrirla sobre una estrategia que ya haya pasado el criterio.
- **Distinto de lo ya descartado**: el calendario de earnings ya se probó como *feature* del modelo (Fases 5–8, hipótesis `[ongoing]` arriba). Esto es un *filtro de riesgo* sobre las órdenes, no una feature nueva. Si se plantea volver a meterlo como feature → no repetir.
- Cambio propuesto: fechas de resultados de `EARNINGS_CALENDAR` (una petición devuelve todas las empresas) + historial de earnings (gratuito) para el backtest; filtro en la ejecución de órdenes.
- Validación: backtest walk-forward de Fase 2, con y sin filtro, mismo periodo y semilla; métricas: max drawdown, Sharpe, nº de operaciones.
- Resultado: —
- Conclusión: —

### [2026-10-14] Descartado sin probar: añadir indicadores macro de AV (Treasury yield, Fed funds, CPI…) como features
- Estado: **NO PRIORITARIO**
- Por qué: es el mismo patrón que la hipótesis macro ya descartada (VIX/SPY, 2026-08-12) y que "sumar features" de las Fases 5–8. Solo se reconsidera si el backtest de Fase 2 muestra ventaja real del modelo base y hay una razón concreta, no "más datos".

### [2026-10-14] Descartado como señal automática: trading-agents.ai / TradingAgents (TauricResearch, multi-agente LLM)
- Estado: **NO INTEGRAR en AlgoTrader**. Uso permitido: segunda opinión manual (informe gratuito, solo NASDAQ-100) antes de ejecutar una señal fuerte.
- Por qué:
  1. No se puede hacer un backtest honesto: el LLM fue entrenado con datos posteriores a la fecha simulada (look-ahead por memorización).
  2. No es reproducible (misma fecha y ticker → salidas distintas); viola la regla de backtest con semilla fija.
  3. Coste por ticker y día (créditos Pro o API propia de LLM) para un scan de 100 símbolos.
  4. La evidencia publicada (arXiv 2412.20138) cubre pocos tickers y un periodo corto.

---

### [2026-10-15] Decisión del usuario: ampliar el universo al S&P 500 y probar otra fuente de información
- Tras 4 enfoques sin ventaja sobre precios diarios del S&P 100, el usuario aprueba (2026-10-15) la "opción 2": información distinta del precio, y **ampliar el universo al S&P 500 actual** (503 valores, `src/data/sp500.py`, congelado de Wikipedia con sector GICS y CIK).
- Nuevo snapshot congelado **`backtest_data/v2_sp500`** (`backtest_fijo.py snapshot --snapshot v2`): mismas fechas que v1 (2010 → 2026-10-13, desarrollo hasta 2025-09-30, holdout después), precios Yahoo ajustados, cierre ajustado solo por splits + splits, fundamentales SEC (companyfacts) y resultados trimestrales (Yahoo). El v1 no se toca: los resultados de 2026-10-14 siguen siendo comparables entre sí.
- **Sesgo de supervivencia MAYOR que en v1**: 500 supervivientes de hoy. Cualquier resultado positivo es optimista; por eso el criterio 2 (IC con t > 2) pesa más que el retorno.
- Mismo criterio de aceptación pre-registrado (1, 2 y 3) y misma regla del holdout. El benchmark es el equiponderado de todo el universo v2.

### [2026-10-15] PRE-REGISTRO H1 — Calidad + valor (fundamentales SEC) · PRIORIDAD 1
- Mecanismo: el mercado infravalora empresas muy rentables respecto a sus activos que además no están caras (Novy-Marx 2013, "The Other Side of Value"; más fuerte en grandes empresas y long-only).
- Datos: SEC companyfacts. Beneficio bruto anual (GrossProfit o ingresos − coste de ventas de la misma presentación, 10-K), activos (10-K), patrimonio (10-K/10-Q), acciones de portada (dei) o diluidas medias si no hay portada; valores < 1e6 acciones descartados (error de escala del emisor). **Point-in-time**: un dato presentado el día F se usa desde F+1; si se reexpresa, cuenta desde la nueva presentación.
- Capitalización = cierre ajustado solo por splits × acciones × producto de splits posteriores a la fecha de las acciones.
- Puntuación en t: rango percentil (beneficio bruto / activos) + rango percentil (patrimonio / capitalización), entre los elegibles del día.
- Elegibles: sector GICS distinto de Financials y Real Estate; ambos ratios conocidos; patrimonio > 0.
- Cartera: top **40**, equiponderada, rebalanceo cada **21** sesiones, entrada open[t+1], salida open[t+1+21]. Coste 0.05% por lado sobre la rotación. Necesita ≥ 80 elegibles en la fecha.
- Limitaciones conocidas: empresas con varias clases de acciones sin dato de portada usan solo las diluidas (GOOGL antes de 2020 queda fuera); empresas sin coste de ventas en XBRL (utilities, restauración) quedan fuera; composición de sectores = la de hoy.
- Intento 1/3. Resultado: —

### [2026-10-15] PRE-REGISTRO H2 — Sorpresa en resultados (PEAD) · PRIORIDAD 2
- Mecanismo: el precio tarda en incorporar del todo una sorpresa en beneficios (Bernard y Thomas 1989). **Prior bajo**: Martineau (2022) no lo encuentra en grandes empresas desde 2006; Subrahmanyam (2025) lo replica sin microcaps con t = 1.43.
- Datos: Yahoo `get_earnings_dates` (BPA estimado, real, % sorpresa y hora). Alpha Vantage `EARNINGS` como respaldo/comprobación (25 peticiones/día).
- Disponibilidad: anuncio antes de las 12:00 NY → se conoce al cierre de ese día; después → al cierre del día hábil siguiente.
- Puntuación en t: % de sorpresa del último anuncio disponible, válido durante **63** sesiones; después NaN.
- Cartera: top **40**, rebalanceo cada **21** sesiones, mismas reglas de ejecución y costes que H1. Necesita ≥ 80 valores con puntuación.
- No solapa con lo descartado: el filtro de earnings de 2026-10-14 solo usaba la *fecha*; esto usa el *tamaño de la sorpresa*.
- Intento 1/3. Resultado: —

### [2026-10-15] REGISTRO H3 — Compras agrupadas de directivos (SEC Form 4) · PRIORIDAD 3
- Mecanismo: los directivos que compran fuera de su patrón habitual tienen información (Cohen, Malloy y Pomorski 2012: +0,82%/mes ponderado por valor en compras "oportunistas"; Alldredge y Blank 2019: compras agrupadas > 2% el mes siguiente).
- Estado: **registrada, sin datos todavía**. Viable solo con el universo ampliado (en el S&P 100 casi no hay compras). Falta un descargador de Form 4 (EDGAR, gratis): ~500 empresas × cientos de formularios.
- Parámetros: ver "PRE-REGISTRO H3" (2026-10-16), fijados antes de descargar los datos.
- Intento 0/3.

### [2026-10-15] Regla de operación de la estrategia principal
- La estrategia elegida como principal en la web (`settings.json` → `strategy`) **no envía órdenes** hasta que su estado en el backtest fijo sea **APROBADA** (criterios 1-2-3 en desarrollo y holdout superado). Hasta entonces la web solo muestra su cartera teórica.

### [2026-10-15] Corrección de H1 ANTES de medir (definición de datos, no ajuste a resultados)
- Al revisar la cartera teórica de hoy (sin haber ejecutado ningún backtest de H1), las aseguradoras de salud salían con beneficio bruto / activos > 1 (ELV 1.46, UNH 1.28): su XBRL no declara los siniestros médicos como coste de ventas, así que "ingresos − coste de ventas" no es un beneficio bruto.
- Regla añadida: se excluyen de H1 las empresas que hayan declarado en algún 10-K costes de siniestros de seguros (`PolicyholderBenefitsAndClaimsIncurredNet`, `…HealthCare`, `BenefitsLossesAndExpenses`). Coherente con excluir financieras (Novy-Marx excluye las financieras por el mismo motivo).
- Verificado: UNH, ELV, CVS, CI, HUM, CNC excluidas; AAPL, KO, JNJ, LLY, WMT no.
- El snapshot v2 se rehízo para guardar esas etiquetas (precios y resultados ya descargados reutilizados). Sigue siendo el intento 1/3 de H1.

#### Resultados H1 y H2 (periodo de desarrollo, snapshot v2 S&P 500, 2026-10-15)
| | Rentab. anual | Benchmark | Sharpe (bench) | Max DD (bench) | IC medio (t) | Acierto (IC95) | Criterios 1/2/3 | Conclusión |
|---|---|---|---|---|---|---|---|---|
| **H1 calidad+valor** (116 rebalanceos) | 19.5% | 18.4% | 1.001 (1.020) | −36.2% (−36.5%) | −0.004 (t −0.41) | 55.6% (54.2–57.1) | ❌ ❌ ✅ | **NO ACEPTADA** |
| **H2 sorpresa resultados** (116 rebalanceos) | 22.0% | 18.4% | 1.009 (1.020) | −43.8% (−36.5%) | **0.016 (t 2.23)** | 56.3% | ❌ ✅ ✅ | **NO ACEPTADA** |

- H1: rentabilidad casi igual al benchmark con el mismo riesgo; el ranking calidad+valor **no ordena** las acciones (IC ≈ 0). Pierde en 2017, 2019, 2024 y 2025. Resultado en `backtest_results/20261015_090852_*_h1_quality_value_v2.json`.
- H2: **primera señal del proyecto con IC significativo** (t = 2.23 > 2), +3.6 puntos/año sobre el benchmark, pero con más volatilidad y caída máxima → Sharpe por debajo (criterio 1 falla por 0.011). Cautela: es la 7.ª estrategia medida en el proyecto; con tantas pruebas, un t = 2.2 puede salir por azar (comparaciones múltiples). Resultado en `backtest_results/20261015_090913_*_h2_earnings_surprise_v2.json`.
- Holdout: **no se ejecuta** para ninguna (solo para lo aceptado en desarrollo).
- Intentos usados: H1 1/3, H2 1/3. Un intento 2 solo con una razón económica escrita ANTES de medir (no variar parámetros a ciegas) y aprobado por el usuario.

### [2026-10-16] PRE-REGISTRO H3 — Compras oportunistas de directivos (SEC Form 4) · PRIORIDAD 3
Aprobado por el usuario ("construye el H3"). Fijado **antes** de descargar ningún dato de Form 4 y de ver ningún resultado.
- Datos: SEC *Insider Transactions Data Sets* (ficheros trimestrales 2006T1 → 2026T3, gratis). Se congelan en `backtest_data/form4_v1/` con su propio manifest (hash). Solo emisores del universo v2 (CIK de `src/data/sp500.py`).
- Operaciones válidas: formulario `4` (sin enmiendas 4/A, que llegan tarde), tabla no derivados, código `P` (compra en mercado abierto) con `A` (adquirida), acciones > 0 y precio > 0. Quien declara debe ser **Director u Officer** (los que solo son "TenPercentOwner"/"Other" no cuentan).
- Disponibilidad: una Form 4 presentada el día F se conoce al cierre del **día hábil siguiente** a F (la SEC solo da la fecha, no la hora).
- Rutinaria u oportunista (Cohen, Malloy y Pomorski 2012, adaptado): la compra de un directivo en el mes m del año Y es **rutinaria** si ese directivo hizo alguna operación en mercado abierto (P o S, en esa empresa) en el mes m de cada uno de los años Y−1, Y−2 e Y−3. Si no, es **oportunista** (también si no hay 3 años de historial; adaptación documentada: el artículo los deja fuera).
- Puntuación en t: nº de directivos distintos con alguna compra oportunista **conocida en las últimas 21 sesiones**, + desempate = importe total comprado ($) / 1e12. Valores sin compras: 0 (no NaN).
- Cartera: los valores con puntuación > 0, máximo los **40** mejores, equiponderados; rebalanceo cada **21** sesiones con las mismas reglas de ejecución y costes (0.05% por lado sobre la rotación real de pesos). Si en una fecha hay **menos de 5** valores con señal, ese periodo se invierte en el benchmark equiponderado (no hay apuesta) y no cuenta para el acierto (criterio 3).
- IC (criterio 2): Spearman entre la puntuación (con los ceros) y el retorno open→open de 21 días en cada rebalanceo, sobre todo el universo.
- Mismo criterio de aceptación (1, 2 y 3), mismo periodo de desarrollo y misma regla del holdout. Se informará también del % de rebalanceos con señal.
- Limitaciones conocidas: sesgo de supervivencia del universo; empresas que cambiaron de CIK (fusiones, nuevas sociedades holding) pierden su historial anterior; el trimestre 2026T4 aún no está publicado (afecta solo a las 2 últimas semanas del holdout).
- Datos congelados: 581.079 operaciones P/S de directivos de 497 emisores (2006-01-03 → 2026-09-30), 28.677 compras, 24.948 oportunistas; ~150-250 empresas con alguna compra cada año.
- Intento 1/3. Resultado (desarrollo, 2026-10-16):

| | Rentab. anual | Benchmark | Sharpe (bench) | Max DD (bench) | IC medio (t) | Acierto (IC95) | Criterios 1/2/3 | Conclusión |
|---|---|---|---|---|---|---|---|---|
| **H3 compras de directivos** (116 rebalanceos, todos con señal; ~25 valores de media) | 20.0% | 18.4% | 0.979 (1.020) | −39.7% (−36.5%) | 0.002 (t 0.35) | 56.7% (54.9–58.5) | ❌ ❌ ✅ | **NO ACEPTADA** |

- Igual que H1: algo más de rentabilidad que el índice con más riesgo, y la puntuación **no ordena** las acciones (IC ≈ 0). En grandes empresas del S&P 500 las compras de directivos no anticipan el mes siguiente; coherente con que la literatura encuentra el efecto sobre todo en empresas pequeñas. Resultado en `backtest_results/20261016_154733_desarrollo_random_forest_h3_insider_buying_v2.json`.
- Holdout: no se ejecuta. Intentos usados: H3 1/3.

