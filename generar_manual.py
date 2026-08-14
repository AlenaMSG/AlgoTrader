"""
Genera el manual de usuario de AlgoTrader en formato Word.
"""
from pathlib import Path
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import io

README = Path(__file__).parent / "Readme"
OUTPUT = README / "Manual_AlgoTrader.docx"

# ── Colores ─────────────────────────────────────────────────────────────────
AZUL        = RGBColor(0x00, 0x77, 0xCC)
AZUL_CLARO  = RGBColor(0x00, 0x99, 0xFF)
VERDE       = RGBColor(0x00, 0x99, 0x55)
ROJO        = RGBColor(0xCC, 0x22, 0x22)
NARANJA     = RGBColor(0xDD, 0x88, 0x00)
GRIS        = RGBColor(0x44, 0x44, 0x55)
NEGRO       = RGBColor(0x1A, 0x1A, 0x2A)
FONDO_TABLA = RGBColor(0xE8, 0xF0, 0xF8)


def set_cell_bg(cell, hex_color: str):
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd  = OxmlElement('w:shd')
    shd.set(qn('w:val'),   'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'),  hex_color)
    tcPr.append(shd)


def heading(doc, text, level=1, color=None):
    p = doc.add_heading(text, level=level)
    if color:
        for run in p.runs:
            run.font.color.rgb = color
    p.paragraph_format.space_before = Pt(14 if level == 1 else 8)
    p.paragraph_format.space_after  = Pt(4)
    return p


def body(doc, text, bold=False, color=None, indent=False):
    p = doc.add_paragraph()
    if indent:
        p.paragraph_format.left_indent = Cm(0.8)
    run = p.add_run(text)
    run.font.size  = Pt(11)
    run.font.bold  = bold
    if color:
        run.font.color.rgb = color
    p.paragraph_format.space_after = Pt(4)
    return p


def info_box(doc, title, content_lines, title_color=None):
    """Caja con fondo de color para destacar información."""
    table = doc.add_table(rows=1, cols=1)
    table.style = 'Table Grid'
    cell = table.cell(0, 0)
    set_cell_bg(cell, 'E8F0F8')
    cell.paragraphs[0].clear()
    tf = cell.paragraphs[0]
    run = tf.add_run(f"  {title}")
    run.font.bold  = True
    run.font.size  = Pt(11)
    run.font.color.rgb = title_color or AZUL
    for line in content_lines:
        p = cell.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.5)
        run = p.add_run(f"• {line}")
        run.font.size = Pt(10)
    doc.add_paragraph()


def col_table(doc, headers, rows, col_widths=None):
    t = doc.add_table(rows=1 + len(rows), cols=len(headers))
    t.style = 'Table Grid'
    t.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Cabecera
    for i, h in enumerate(headers):
        cell = t.cell(0, i)
        set_cell_bg(cell, '0077CC')
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(h)
        run.font.bold  = True
        run.font.size  = Pt(10)
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    # Filas
    for ri, row in enumerate(rows):
        bg = 'F0F5FF' if ri % 2 == 0 else 'FFFFFF'
        for ci, val in enumerate(row):
            cell = t.cell(ri + 1, ci)
            set_cell_bg(cell, bg)
            p = cell.paragraphs[0]
            if ci == 0:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = p.add_run(val)
                run.font.bold = True
                run.font.size = Pt(10)
            else:
                run = p.add_run(val)
                run.font.size = Pt(10)

    if col_widths:
        for i, w in enumerate(col_widths):
            for row in t.rows:
                row.cells[i].width = Inches(w)

    doc.add_paragraph()
    return t


# ═══════════════════════════════════════════════════════════════════════════
#  CONSTRUCCIÓN DEL DOCUMENTO
# ═══════════════════════════════════════════════════════════════════════════
def build():
    doc = Document()

    # Márgenes
    for section in doc.sections:
        section.top_margin    = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin   = Cm(3)
        section.right_margin  = Cm(2.5)

    # ── Portada ─────────────────────────────────────────────────────────────
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("AlgoTrader")
    run.font.size  = Pt(36)
    run.font.bold  = True
    run.font.color.rgb = AZUL

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Manual de Usuario")
    run.font.size  = Pt(18)
    run.font.color.rgb = GRIS

    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(
        "Herramienta de análisis bursátil con Inteligencia Artificial\n"
        "XGBoost · Yahoo Finance · Alpaca Markets · Paper Trading"
    )
    run.font.size  = Pt(12)
    run.font.italic = True
    run.font.color.rgb = GRIS

    doc.add_page_break()

    # ── 1. ¿Qué es AlgoTrader? ───────────────────────────────────────────────
    heading(doc, "1. ¿Qué es AlgoTrader?", 1, AZUL)
    body(doc,
         "AlgoTrader es una aplicación de escritorio que utiliza Inteligencia Artificial "
         "para analizar acciones del mercado bursátil estadounidense y generar señales de "
         "compra o venta. No opera dinero real — utiliza el modo Paper Trading de Alpaca "
         "(dinero simulado) para que puedas aprender y experimentar sin riesgo.")
    doc.add_paragraph()
    body(doc, "¿Cómo funciona en resumen?", bold=True)
    info_box(doc, "Proceso de análisis:", [
        "Descarga el historial de precios del activo (hasta 15+ años) desde Yahoo Finance.",
        "Calcula indicadores técnicos: RSI, MACD, Bandas de Bollinger, ATR y retornos logarítmicos.",
        "Entrena un modelo de Inteligencia Artificial (XGBoost) con esos datos históricos.",
        "El modelo aprende patrones del pasado para predecir si el precio subirá o bajará mañana.",
        "Muestra la señal (COMPRAR / VENDER / NEUTRAL) junto con el precio actual del mercado.",
        "Guarda el modelo entrenado en disco — no necesitas reentrenar cada vez que abres la app.",
    ])

    # ── 2. Pantalla principal ────────────────────────────────────────────────
    heading(doc, "2. Pantalla principal", 1, AZUL)
    body(doc,
         "La pantalla se divide en cuatro zonas principales: la barra de herramientas "
         "(superior), la tabla comparativa, el gráfico de precios y el panel de detalle.")

    doc.add_picture(str(Path("Readme/screenshot_main.png")), width=Inches(5.5)) if \
        Path("Readme/screenshot_main.png").exists() else None

    # ── 3. Barra de herramientas ─────────────────────────────────────────────
    heading(doc, "3. Barra de herramientas", 1, AZUL)

    col_table(doc,
        ["Campo", "Descripción", "Ejemplo"],
        [
            ["Símbolo(s)",
             "Escribe el ticker (código) del activo que quieres analizar. "
             "Puedes poner varios separados por coma.",
             "AAPL, TSLA, NVDA"],
            ["Desde",
             "Fecha de inicio del historial de precios para entrenar el modelo. "
             "Cuanto más atrás, más datos tiene el modelo para aprender. "
             "Formato: AAAA-MM-DD.",
             "2010-01-01"],
            ["▶ Entrenar y Analizar",
             "Inicia el proceso completo: descarga datos, calcula indicadores, "
             "entrena el modelo XGBoost y genera la señal.",
             "—"],
        ],
        col_widths=[1.3, 3.5, 1.5],
    )

    info_box(doc, "¿Qué tickers puedo usar?", [
        "Acciones americanas: AAPL (Apple), MSFT (Microsoft), NVDA (Nvidia), TSLA (Tesla), AMZN (Amazon)...",
        "ETFs: SPY (S&P 500), QQQ (Nasdaq 100), DIA (Dow Jones)...",
        "Solo funciona con activos que cotizan en bolsas americanas (NYSE, NASDAQ).",
    ])

    # ── 4. Tabla comparativa ─────────────────────────────────────────────────
    heading(doc, "4. Tabla comparativa de símbolos", 1, AZUL)
    body(doc,
         "Una vez completado el análisis, la tabla muestra un resumen de todos los "
         "activos analizados de un vistazo. Puedes hacer clic en cualquier fila para "
         "ver el detalle de ese activo en el gráfico y el panel derecho.")
    doc.add_paragraph()

    col_table(doc,
        ["Columna", "Qué significa", "Posibles valores"],
        [
            ["Símbolo",
             "Código del activo en bolsa.",
             "AAPL, TSLA, SPY…"],
            ["Señal",
             "Recomendación del modelo de IA basada en los patrones históricos. "
             "Es una sugerencia, no una garantía.",
             "COMPRAR\nCOMPRAR (débil)\nNEUTRAL\nVENDER (débil)\nVENDER"],
            ["Prob. Subida",
             "Probabilidad en % de que el precio cierre más alto mañana "
             "según el modelo. Por encima de 65% → COMPRAR. "
             "Por debajo de 35% → VENDER.",
             "0% – 100%"],
            ["Ask",
             "Precio al que puedes COMPRAR el activo ahora mismo en el mercado. "
             "Es el precio que pide el vendedor.",
             "$182.5200"],
            ["Bid",
             "Precio al que puedes VENDER el activo ahora mismo. "
             "Es el precio que ofrece el comprador. Siempre ligeramente inferior al Ask.",
             "$182.5000"],
            ["Precisión CV",
             "Porcentaje de aciertos del modelo, medido con datos que NO usó "
             "durante el entrenamiento (validación cruzada temporal). "
             "Un valor de 55-65% es normal en mercados financieros.",
             "52.3% ±3.1%"],
            ["Estado",
             "Indica en qué punto está el análisis de ese símbolo.",
             "En proceso…\nCompletado ✓\nError: [motivo]"],
        ],
        col_widths=[1.1, 3.2, 1.8],
    )

    info_box(doc, "Código de colores de la señal:", [
        "Verde  → COMPRAR: el modelo predice subida con alta confianza (prob. > 65%).",
        "Rojo   → VENDER: el modelo predice bajada con alta confianza (prob. < 35%).",
        "Naranja → NEUTRAL o señal débil: no hay suficiente certeza para actuar.",
    ])

    # ── 5. Gráfico de precios ────────────────────────────────────────────────
    heading(doc, "5. Gráfico de precios", 1, AZUL)
    body(doc,
         "El gráfico muestra la evolución histórica del precio de cierre del activo "
         "seleccionado. Al hacer clic en una fila de la tabla, el gráfico se actualiza "
         "automáticamente para mostrar ese activo.")
    doc.add_paragraph()
    body(doc, "¿Qué muestra exactamente?", bold=True)
    info_box(doc, "Elementos del gráfico:", [
        "Línea de precio: evolución del precio de cierre diario desde la fecha de inicio.",
        "Eje X (horizontal): tiempo (fechas).",
        "Eje Y (vertical): precio del activo en dólares ($).",
        "Cuanto más años de historial hayas seleccionado, más larga es la línea.",
        "Los datos provienen de Yahoo Finance (histórico) combinados con Alpaca (datos recientes).",
    ])

    # ── 6. Panel derecho ────────────────────────────────────────────────────
    heading(doc, "6. Panel derecho — Detalle del activo seleccionado", 1, AZUL)
    body(doc,
         "Al hacer clic en cualquier fila de la tabla, el panel derecho muestra el "
         "análisis detallado de ese activo. Se divide en tres secciones:")

    # 6.1 Señal
    heading(doc, "6.1  Señal y cotización en tiempo real", 2, AZUL_CLARO)
    body(doc,
         "La parte superior del panel muestra la señal del modelo y los precios "
         "actuales obtenidos de Alpaca en tiempo real.")
    col_table(doc,
        ["Elemento", "Descripción"],
        [
            ["Señal grande\n(COMPRAR / VENDER / NEUTRAL)",
             "Recomendación del modelo XGBoost. Se muestra en verde si es COMPRAR, "
             "en rojo si es VENDER y en naranja si es NEUTRAL o señal débil."],
            ["Probabilidad de subida",
             "Confianza del modelo en que el precio subirá mañana. "
             "Por encima del 65% activa COMPRAR, por debajo del 35% activa VENDER."],
            ["Ask",
             "Precio actual al que puedes comprar el activo (precio del vendedor). "
             "Dato en tiempo real de Alpaca."],
            ["Bid",
             "Precio actual al que puedes vender (precio del comprador). "
             "Siempre algo menor que el Ask. La diferencia se llama 'spread'."],
            ["Sugerencia de precio límite",
             "Precio recomendado para colocar una orden límite: "
             "Bid + $0.01 para comprar (ligeramente mejor que el mercado), "
             "Ask − $0.01 para vender."],
        ],
        col_widths=[2.0, 4.0],
    )

    # 6.2 Métricas
    heading(doc, "6.2  Métricas del modelo (XGBoost)", 2, AZUL_CLARO)
    body(doc,
         "Esta sección muestra cómo de bien funciona el modelo entrenado. "
         "Es importante para saber si puedes confiar en las señales que genera.")
    col_table(doc,
        ["Métrica", "Qué mide", "Cómo interpretar"],
        [
            ["Precisión CV\n(Media ± Desviación)",
             "Porcentaje de predicciones correctas medido con el método "
             "TimeSeriesSplit: el modelo se entrena con datos del pasado "
             "y se prueba con datos del futuro, simulando uso real.",
             "55-60% = aceptable.\n60-65% = bueno.\n>65% = excelente.\n"
             "Un modelo perfecto sería imposible en bolsa."],
            ["AUC CV",
             "Area Under the Curve. Mide qué tan bien separa el modelo "
             "los días que suben de los que bajan. "
             "0.5 = azar puro, 1.0 = modelo perfecto.",
             "< 0.52 = apenas mejor que azar.\n"
             "0.55-0.60 = útil.\n> 0.60 = muy bueno."],
            ["Precisión entren.",
             "Precisión sobre los datos con los que aprendió. "
             "Suele ser más alta que la CV — no es tan fiable.",
             "Solo informativa. Si es mucho mayor que CV, el modelo puede "
             "estar 'memorizando' en lugar de aprender."],
            ["Precisión compra",
             "De todas las veces que el modelo dijo COMPRAR, "
             "¿cuántas veces tenía razón y el precio realmente subió?",
             "Por encima del 55% es positivo."],
            ["Recall compra",
             "De todas las subidas reales que hubo, "
             "¿qué porcentaje detectó el modelo?",
             "Un recall bajo significa que el modelo se pierde muchas subidas."],
            ["Muestras",
             "Total de días de histórico usados para entrenar el modelo. "
             "Más muestras = modelo más robusto.",
             "Con 10 años de datos diarios: ~2.500 muestras por símbolo."],
        ],
        col_widths=[1.5, 2.8, 1.8],
    )

    # 6.3 Top Features
    heading(doc, "6.3  Top Features (importancia de indicadores)", 2, AZUL_CLARO)
    body(doc,
         "Muestra qué indicadores técnicos son los más importantes para que el modelo "
         "tome sus decisiones sobre ese activo concreto. El porcentaje indica cuánto "
         "peso le da el modelo a cada indicador.")
    doc.add_paragraph()

    col_table(doc,
        ["Indicador", "Qué es", "Qué mide"],
        [
            ["log_ret_1d / 5d / 20d",
             "Retorno logarítmico",
             "Cambio de precio en 1, 5 o 20 días. Si aparece arriba de la lista, "
             "el precio reciente es el mejor predictor para ese activo."],
            ["rsi",
             "RSI (Índice de Fuerza Relativa, 14 días)",
             "Mide si el activo está sobrecomprado (>70) o sobrevendido (<30). "
             "Muy popular entre traders para detectar rebotes."],
            ["macd / macd_signal / macd_hist",
             "MACD (12, 26, 9)",
             "Diferencia entre dos medias móviles exponenciales. "
             "Indica cambios de tendencia. Cuando el MACD cruza la señal → "
             "posible cambio de dirección."],
            ["bb_upper / bb_lower / bb_pct",
             "Bandas de Bollinger (20, 2σ)",
             "Si el precio toca la banda superior → puede estar sobrecomprado. "
             "Si toca la inferior → puede estar sobrevendido. "
             "bb_pct indica dónde está el precio dentro de las bandas (0=abajo, 1=arriba)."],
            ["atr",
             "ATR (Average True Range, 14 días)",
             "Mide la volatilidad media. Un ATR alto significa que el precio "
             "se mueve mucho (mayor riesgo y mayor oportunidad)."],
            ["sma20 / sma50 / sma_ratio",
             "Medias Móviles Simples",
             "Precio medio de los últimos 20 y 50 días. "
             "Cuando sma20 > sma50 → tendencia alcista. "
             "sma_ratio = sma20 / sma50 (>1 alcista, <1 bajista)."],
            ["vol_ratio",
             "Ratio de volumen",
             "Volumen actual respecto a la media de 20 días. "
             "Un volumen muy alto acompañando a un movimiento de precio confirma la señal."],
            ["close",
             "Precio de cierre",
             "El precio de cierre del último día disponible."],
        ],
        col_widths=[1.6, 1.8, 2.7],
    )

    info_box(doc, "Nota sobre los top features:", [
        "Los features más importantes varían por activo. AAPL puede depender más del MACD "
        "mientras que TSLA puede depender más de la volatilidad (ATR).",
        "Si 'close' aparece muy arriba, el modelo está usando el precio bruto — "
        "esto puede ser señal de que necesita más datos históricos.",
        "Un feature con >15% de importancia es dominante. Una distribución equilibrada "
        "entre varios indicadores suele indicar un modelo más robusto.",
    ])

    # ── 7. Guía de uso paso a paso ───────────────────────────────────────────
    heading(doc, "7. Guía de uso paso a paso", 1, AZUL)

    steps = [
        ("Paso 1: Abre la aplicación",
         "Ejecuta AlgoTrader.bat desde la carpeta del proyecto. "
         "La ventana principal se abrirá con el símbolo AAPL por defecto."),
        ("Paso 2: Introduce los símbolos",
         "En el campo 'Símbolo(s)' escribe los tickers que quieres analizar "
         "separados por coma. Ejemplo: AAPL, TSLA, NVDA, SPY"),
        ("Paso 3: Selecciona la fecha de inicio",
         "En el campo 'Desde' escribe la fecha desde la que quieres tomar datos históricos. "
         "Se recomienda al menos 5 años (2018-01-01) para un buen entrenamiento. "
         "Puedes ir hasta 1993 para índices como SPY o QQQ."),
        ("Paso 4: Pulsa Entrenar y Analizar",
         "El proceso tarda entre 20-60 segundos por símbolo dependiendo de los años "
         "de historial y la velocidad de tu ordenador. "
         "Puedes seguir el progreso en la barra de estado (parte inferior)."),
        ("Paso 5: Interpreta los resultados",
         "Observa la tabla: los símbolos con señal COMPRAR (verde) son los que el modelo "
         "predice que subirán mañana. Haz clic en cada fila para ver el detalle "
         "en el panel derecho y el gráfico histórico."),
        ("Paso 6: Próximas sesiones",
         "El modelo entrenado queda guardado en la carpeta 'models/'. "
         "Los datos históricos se guardan en 'data_cache/'. "
         "La próxima vez que abras la app y analices los mismos símbolos, "
         "será más rápido porque no descargará los datos desde cero."),
    ]

    for title, text in steps:
        p = doc.add_paragraph(style='List Number')
        run = p.add_run(title + "\n")
        run.font.bold = True
        run.font.size = Pt(11)
        run.font.color.rgb = AZUL
        run2 = p.add_run(text)
        run2.font.size = Pt(11)
        p.paragraph_format.space_after = Pt(6)

    doc.add_paragraph()

    # ── 8. Preguntas frecuentes ──────────────────────────────────────────────
    heading(doc, "8. Preguntas frecuentes", 1, AZUL)

    faqs = [
        ("¿El modelo siempre acierta?",
         "No. Ningún modelo puede predecir la bolsa con certeza. Una precisión del 58-62% "
         "ya es considerada buena en trading algorítmico. El objetivo no es acertar siempre, "
         "sino tener una pequeña ventaja estadística a largo plazo."),
        ("¿Por qué tarda tanto en entrenar?",
         "El modelo analiza miles de filas de datos históricos y realiza 5 rondas de "
         "validación cruzada. Con 10 años de datos y 10 símbolos puede tardar 3-8 minutos. "
         "Es una operación puntual — el resultado se guarda en disco."),
        ("¿Cuántos años de historial debo usar?",
         "Se recomienda entre 5 y 15 años. Con menos de 3 años el modelo no tiene suficientes "
         "ejemplos de distintos ciclos de mercado (subidas, bajadas, crisis). Con más de 15 "
         "años los patrones más antiguos pueden estar 'caducados'."),
        ("¿Qué significa Paper Trading?",
         "Es una simulación con dinero ficticio. Alpaca proporciona un entorno idéntico al "
         "mercado real pero sin usar dinero real. Perfecto para aprender y probar estrategias "
         "sin riesgo económico."),
        ("¿Puedo añadir más indicadores técnicos?",
         "Sí. El archivo src/analysis/feature_engineer.py contiene todos los indicadores. "
         "Puedes añadir cualquier indicador disponible en la librería pandas_ta."),
        ("¿Cómo sé si puedo confiar en una señal?",
         "Combina tres factores: (1) Precisión CV > 57%, (2) AUC > 0.55, "
         "(3) Probabilidad de subida bien alejada del 50% (>60% o <40%). "
         "Si los tres se cumplen, la señal tiene más respaldo estadístico."),
    ]

    for pregunta, respuesta in faqs:
        p = doc.add_paragraph()
        run = p.add_run(f"❓  {pregunta}")
        run.font.bold  = True
        run.font.size  = Pt(11)
        run.font.color.rgb = AZUL
        p.paragraph_format.space_after = Pt(2)

        p2 = doc.add_paragraph()
        p2.paragraph_format.left_indent = Cm(0.8)
        run2 = p2.add_run(respuesta)
        run2.font.size = Pt(11)
        p2.paragraph_format.space_after = Pt(8)

    # ── 9. Glosario ──────────────────────────────────────────────────────────
    heading(doc, "9. Glosario de términos", 1, AZUL)
    col_table(doc,
        ["Término", "Definición"],
        [
            ["XGBoost",       "Algoritmo de Machine Learning basado en árboles de decisión con boosting. "
                              "Uno de los más usados en competiciones de IA y finanzas cuantitativas."],
            ["TimeSeriesSplit","Técnica de validación que respeta el orden temporal: siempre se entrena "
                               "con datos del pasado y se valida con datos del futuro. Evita el 'trampa' "
                               "de usar datos futuros para predecir el pasado."],
            ["RSI",           "Relative Strength Index. Oscilador de momentum entre 0 y 100. "
                              ">70 = sobrecomprado (puede bajar), <30 = sobrevendido (puede subir)."],
            ["MACD",          "Moving Average Convergence Divergence. Diferencia entre la media "
                              "exponencial de 12 días y 26 días. Indica cambios de tendencia."],
            ["ATR",           "Average True Range. Mide la volatilidad promedio de los últimos 14 días. "
                              "Cuanto mayor, más se mueve el precio."],
            ["Bollinger Bands","Tres líneas alrededor del precio: media móvil de 20 días ± 2 desviaciones "
                               "típicas. El precio suele mantenerse dentro de las bandas el 95% del tiempo."],
            ["Ask / Bid",     "Ask = precio de venta del mercado (lo que pagas al comprar). "
                              "Bid = precio de compra del mercado (lo que recibes al vender). "
                              "La diferencia (spread) es el coste implícito de la operación."],
            ["Paper Trading", "Operativa simulada con dinero ficticio. Idéntica al mercado real "
                              "pero sin riesgo económico."],
            ["AUC",           "Area Under the ROC Curve. Métrica de calidad de un clasificador binario. "
                              "0.5 = azar, 1.0 = perfecto. En bolsa, >0.55 ya es útil."],
            ["Log Return",    "Retorno logarítmico: log(precio_hoy / precio_ayer). "
                              "Estadísticamente más estable que el retorno porcentual simple."],
            ["Feature",       "Variable de entrada del modelo. Cada indicador técnico "
                              "(RSI, MACD, etc.) es un feature. El modelo combina todos para decidir."],
        ],
        col_widths=[1.4, 4.7],
    )

    # ── Pie de página ─────────────────────────────────────────────────────────
    doc.add_page_break()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(
        "AlgoTrader  —  Herramienta educativa de trading algorítmico\n"
        "Generado automáticamente · Solo para Paper Trading · No constituye asesoramiento financiero"
    )
    run.font.size   = Pt(9)
    run.font.italic = True
    run.font.color.rgb = GRIS

    doc.save(str(OUTPUT))
    print(f"Manual guardado en: {OUTPUT}")


if __name__ == "__main__":
    build()
