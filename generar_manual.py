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


def bullet_list(doc, lines, size=11):
    """Lista de viñetas simple (sin caja de fondo)."""
    for line in lines:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.6)
        p.paragraph_format.space_after = Pt(4)
        run = p.add_run(f"• {line}")
        run.font.size = Pt(size)
    return


IMG_DIR = README / "img"


def screenshot(doc, filename, width=6.0, caption=None):
    """Inserta una captura de pantalla del dashboard, centrada, con pie opcional."""
    path = IMG_DIR / filename
    if not path.exists():
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    run.add_picture(str(path), width=Inches(width))
    if caption:
        cap = doc.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        crun = cap.add_run(caption)
        crun.font.size   = Pt(9)
        crun.font.italic = True
        crun.font.color.rgb = GRIS
    doc.add_paragraph()


def add_toc(doc):
    """
    Inserta un campo TOC (Tabla de Contenido) nativo de Word, generado a partir
    de los estilos Heading 1/2/3. Al abrir el documento, Word actualiza el
    campo automáticamente (gracias a settings.updateFields) y cada entrada
    queda enlazada: Ctrl+clic salta directamente a ese epígrafe.
    """
    paragraph = doc.add_paragraph()
    run = paragraph.add_run()

    fld_begin = OxmlElement('w:fldChar')
    fld_begin.set(qn('w:fldCharType'), 'begin')

    instr = OxmlElement('w:instrText')
    instr.set(qn('xml:space'), 'preserve')
    instr.text = 'TOC \\o "1-2" \\h \\z \\u'

    fld_separate = OxmlElement('w:fldChar')
    fld_separate.set(qn('w:fldCharType'), 'separate')

    placeholder = OxmlElement('w:t')
    placeholder.text = "Haz clic con el botón derecho aquí y elige “Actualizar campo” para generar el índice."

    fld_end = OxmlElement('w:fldChar')
    fld_end.set(qn('w:fldCharType'), 'end')

    r = run._r
    r.append(fld_begin)
    r.append(instr)
    r.append(fld_separate)
    r.append(placeholder)
    r.append(fld_end)

    # Forzar la actualización automática de todos los campos (incluido este
    # TOC) en cuanto Word abre el documento, para que ya salga rellenado.
    settings = doc.settings.element
    update_fields = OxmlElement('w:updateFields')
    update_fields.set(qn('w:val'), 'true')
    settings.append(update_fields)


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


# ── Referencia de tickers S&P 100 (usada en 2.5) ─────────────────────────────
SP100_REFERENCE = [
    ["AAPL", "Apple", "Tecnología", "EE.UU."],
    ["MSFT", "Microsoft", "Tecnología", "EE.UU."],
    ["NVDA", "NVIDIA", "Tecnología", "EE.UU."],
    ["AVGO", "Broadcom", "Tecnología", "EE.UU."],
    ["ORCL", "Oracle", "Tecnología", "EE.UU."],
    ["CSCO", "Cisco Systems", "Tecnología", "EE.UU."],
    ["IBM", "IBM", "Tecnología", "EE.UU."],
    ["INTC", "Intel", "Tecnología", "EE.UU."],
    ["TXN", "Texas Instruments", "Tecnología", "EE.UU."],
    ["QCOM", "Qualcomm", "Tecnología", "EE.UU."],
    ["ADI", "Analog Devices", "Tecnología", "EE.UU."],
    ["AMAT", "Applied Materials", "Tecnología", "EE.UU."],
    ["NOW", "ServiceNow", "Tecnología", "EE.UU."],
    ["ADBE", "Adobe", "Tecnología", "EE.UU."],
    ["CRM", "Salesforce", "Tecnología", "EE.UU."],
    ["INTU", "Intuit", "Tecnología", "EE.UU."],
    ["GOOGL", "Alphabet (Google)", "Comunicaciones", "EE.UU."],
    ["META", "Meta Platforms", "Comunicaciones", "EE.UU."],
    ["T", "AT&T", "Telecomunicaciones", "EE.UU."],
    ["VZ", "Verizon", "Telecomunicaciones", "EE.UU."],
    ["AMZN", "Amazon", "Consumo disc. / Tecnol.", "EE.UU."],
    ["TSLA", "Tesla", "Automoción / Energía", "EE.UU."],
    ["MCD", "McDonald's", "Restauración", "EE.UU."],
    ["NKE", "Nike", "Ropa y calzado", "EE.UU."],
    ["LOW", "Lowe's", "Mejoras del hogar", "EE.UU."],
    ["HD", "Home Depot", "Mejoras del hogar", "EE.UU."],
    ["SBUX", "Starbucks", "Restauración", "EE.UU."],
    ["TGT", "Target", "Comercio minorista", "EE.UU."],
    ["BKNG", "Booking Holdings", "Viajes online", "EE.UU."],
    ["PG", "Procter & Gamble", "Consumo básico", "EE.UU."],
    ["KO", "Coca-Cola", "Bebidas", "EE.UU."],
    ["PEP", "PepsiCo", "Bebidas / Snacks", "EE.UU."],
    ["WMT", "Walmart", "Comercio minorista", "EE.UU."],
    ["COST", "Costco", "Comercio minorista", "EE.UU."],
    ["PM", "Philip Morris", "Tabaco", "EE.UU."],
    ["MO", "Altria Group", "Tabaco", "EE.UU."],
    ["MDLZ", "Mondelez International", "Alimentación", "EE.UU."],
    ["CL", "Colgate-Palmolive", "Higiene / Consumo básico", "EE.UU."],
    ["UNH", "UnitedHealth Group", "Seguros de salud", "EE.UU."],
    ["JNJ", "Johnson & Johnson", "Farmacéutica / Dispositivos", "EE.UU."],
    ["LLY", "Eli Lilly", "Farmacéutica", "EE.UU."],
    ["ABBV", "AbbVie", "Farmacéutica / Biotech", "EE.UU."],
    ["MRK", "Merck", "Farmacéutica", "EE.UU."],
    ["ABT", "Abbott Laboratories", "Dispositivos médicos", "EE.UU."],
    ["TMO", "Thermo Fisher Scientific", "Ciencias de la vida", "EE.UU."],
    ["DHR", "Danaher", "Ciencias de la vida", "EE.UU."],
    ["BMY", "Bristol-Myers Squibb", "Farmacéutica", "EE.UU."],
    ["AMGN", "Amgen", "Biotecnología", "EE.UU."],
    ["GILD", "Gilead Sciences", "Biotecnología", "EE.UU."],
    ["ISRG", "Intuitive Surgical", "Robótica médica", "EE.UU."],
    ["MDT", "Medtronic", "Dispositivos médicos", "Irlanda *"],
    ["SYK", "Stryker", "Dispositivos médicos", "EE.UU."],
    ["ZTS", "Zoetis", "Salud animal", "EE.UU."],
    ["BDX", "Becton Dickinson", "Dispositivos médicos", "EE.UU."],
    ["CVS", "CVS Health", "Farmacia / Seguros", "EE.UU."],
    ["CI", "Cigna", "Seguros de salud", "EE.UU."],
    ["ELV", "Elevance Health", "Seguros de salud", "EE.UU."],
    ["VRTX", "Vertex Pharmaceuticals", "Biotecnología", "EE.UU."],
    ["JPM", "JPMorgan Chase", "Banca", "EE.UU."],
    ["BAC", "Bank of America", "Banca", "EE.UU."],
    ["WFC", "Wells Fargo", "Banca", "EE.UU."],
    ["MS", "Morgan Stanley", "Banca de inversión", "EE.UU."],
    ["GS", "Goldman Sachs", "Banca de inversión", "EE.UU."],
    ["BLK", "BlackRock", "Gestión de activos", "EE.UU."],
    ["SCHW", "Charles Schwab", "Servicios financieros", "EE.UU."],
    ["USB", "U.S. Bancorp", "Banca", "EE.UU."],
    ["PNC", "PNC Financial Services", "Banca", "EE.UU."],
    ["TFC", "Truist Financial", "Banca", "EE.UU."],
    ["COF", "Capital One", "Servicios financieros", "EE.UU."],
    ["C", "Citigroup", "Banca", "EE.UU."],
    ["AXP", "American Express", "Pagos / Servicios finan.", "EE.UU."],
    ["CME", "CME Group", "Mercados financieros", "EE.UU."],
    ["SPGI", "S&P Global", "Información financiera", "EE.UU."],
    ["AON", "Aon", "Seguros / Consultoría", "Irlanda *"],
    ["MMC", "Marsh & McLennan", "Seguros / Consultoría", "EE.UU."],
    ["XOM", "ExxonMobil", "Energía / Petróleo", "EE.UU."],
    ["CVX", "Chevron", "Energía / Petróleo", "EE.UU."],
    ["EOG", "EOG Resources", "Energía / Gas", "EE.UU."],
    ["SLB", "SLB (Schlumberger)", "Servicios petroleros", "EE.UU."],
    ["FCX", "Freeport-McMoRan", "Minería / Cobre", "EE.UU."],
    ["HON", "Honeywell", "Industrial / Aeroespacial", "EE.UU."],
    ["CAT", "Caterpillar", "Maquinaria pesada", "EE.UU."],
    ["DE", "John Deere", "Maquinaria agrícola", "EE.UU."],
    ["BA", "Boeing", "Aeroespacial / Defensa", "EE.UU."],
    ["GE", "GE Aerospace", "Aeroespacial / Motores", "EE.UU."],
    ["UPS", "United Parcel Service", "Logística / Paquetería", "EE.UU."],
    ["RTX", "RTX Corporation", "Aeroespacial / Defensa", "EE.UU."],
    ["ETN", "Eaton", "Gestión de energía", "Irlanda *"],
    ["ITW", "Illinois Tool Works", "Industrial diversificado", "EE.UU."],
    ["FDX", "FedEx", "Logística / Paquetería", "EE.UU."],
    ["LIN", "Linde", "Gases industriales", "Reino Unido *"],
    ["PLD", "Prologis", "Real Estate / Logística", "EE.UU."],
    ["AMT", "American Tower", "Infraestructura / Torres", "EE.UU."],
    ["NEE", "NextEra Energy", "Energías renovables", "EE.UU."],
    ["DUK", "Duke Energy", "Electricidad / Gas", "EE.UU."],
    ["SO", "Southern Company", "Electricidad / Gas", "EE.UU."],
    ["V", "Visa", "Pagos", "EE.UU."],
    ["MA", "Mastercard", "Pagos", "EE.UU."],
    ["ACN", "Accenture", "Tecnología / Consultoría", "Irlanda *"],
    ["ADP", "ADP", "Tecnología / RRHH", "EE.UU."],
]


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

    # ── Índice (página 2) ─────────────────────────────────────────────────────
    # Título con aspecto de "Heading 1" pero SIN el estilo real, para que el
    # propio campo TOC no se liste a sí mismo como primera entrada.
    p_idx = doc.add_paragraph()
    run_idx = p_idx.add_run("Índice")
    run_idx.font.size = Pt(20)
    run_idx.font.bold = True
    run_idx.font.color.rgb = AZUL
    p_idx.paragraph_format.space_after = Pt(10)

    add_toc(doc)
    doc.add_page_break()

    # ── 1. ¿Qué es AlgoTrader? ───────────────────────────────────────────────
    heading(doc, "1. ¿Qué es AlgoTrader?", 1, AZUL)
    body(doc,
         "AlgoTrader es una aplicación de escritorio que utiliza Inteligencia Artificial "
         "para analizar acciones del mercado bursátil estadounidense y generar señales de "
         "compra o venta. No opera dinero real — utiliza el modo Paper Trading de Alpaca "
         "(dinero simulado) para que puedas aprender y experimentar sin riesgo.")

    # ── 2. Pestaña Inicio ─────────────────────────────────────────────────────
    heading(doc, "2. Pestaña Inicio", 1, AZUL)
    body(doc,
         "La pestaña Inicio es la pantalla principal del dashboard. Muestra en un solo "
         "vistazo el estado de tu cuenta y las últimas señales de trading generadas por "
         "el sistema.")

    # 2.1 Tarjetas de resumen
    heading(doc, "2.1  Tarjetas de resumen de cuenta", 2, AZUL_CLARO)
    body(doc,
         "Las 4 tarjetas se actualizan automáticamente cada 30 segundos con datos en "
         "tiempo real de tu cuenta de simulación en Alpaca. Son:")
    screenshot(doc, "inicio_kpis.png", width=6.3, caption="Tarjetas de resumen de cuenta.")
    bullet_list(doc, [
        "Valor de tu cartera: Total de tu cuenta en este momento: todo tu efectivo más "
        "el valor actual de las acciones que tienes compradas. Ejemplo: 5.000 $ en "
        "efectivo + acciones por valor de 3.000 $ = cartera de 8.000 $.",
        "Efectivo disponible: Dinero en tu cuenta que no está invertido en ninguna "
        "acción. Es lo que puedes usar para comprar ahora mismo. Sube cuando vendes "
        "una acción y baja cuando compras una.",
        "Capacidad de compra: Importe máximo que puedes gastar en este momento. En "
        "modo simulación el sistema te presta el doble de tu efectivo, por eso suele "
        "ser mayor que el efectivo disponible. Ejemplo: con 5.000 $ en efectivo, la "
        "capacidad de compra es 10.000 $.",
        "Ganancia / Pérdida (7 días): Cuánto has ganado o perdido en los últimos 7 días "
        "comparando el valor de hoy con el de hace una semana. Verde con \"+\" = "
        "ganaste. Rojo con \"−\" = perdiste. Ejemplo: +127,50 $ (+1,32 %) significa que "
        "ganaste 127,50 dólares esta semana.",
    ])
    doc.add_paragraph()
    body(doc, "Cálculo de la Ganancia/Pérdida de 7 días:", bold=True)
    body(doc,
         "Alpaca guarda el historial del valor de tu cartera día a día. Lo que hace el "
         "sistema es muy sencillo:")

    for i, step in enumerate([
        "Mira cuánto valía tu cartera hace exactamente 7 días",
        "Mira cuánto vale ahora mismo",
        "Resta uno del otro",
    ], start=1):
        p = doc.add_paragraph(style='List Number')
        run = p.add_run(step)
        run.font.size = Pt(11)
        p.paragraph_format.space_after = Pt(2)

    doc.add_paragraph()
    body(doc,
         "Ejemplo: si hace 7 días tenías 10.000 $ y hoy tienes 10.127,50 $, el "
         "resultado es +127,50 $ (+1,32 %).")
    body(doc,
         "El porcentaje sale de dividir esa diferencia entre el valor de hace 7 días y "
         "multiplicar por 100.")
    body(doc,
         "Mide si tu cartera en conjunto ha crecido o encogido durante la última "
         "semana, contando tanto el efectivo que tienes sin invertir como el valor "
         "actual de las acciones que tienes compradas.")

    # 2.2 Tabla de señales
    heading(doc, "2.2  Tabla de señales", 2, AZUL_CLARO)
    body(doc,
         "Muestra las señales del último análisis automático, que se ejecuta cada día "
         "laborable a las 14:45. Cada fila representa una acción del S&P 100 "
         "analizada. Las columnas son:")
    screenshot(doc, "inicio_tabla.png", width=6.3, caption="Tabla de señales de la Pestaña Inicio.")
    bullet_list(doc, [
        "Acción: El código de la empresa analizada (ticker). Ejemplo: AAPL = Apple, "
        "MSFT = Microsoft.",
        "Señal: La recomendación del sistema. COMPRAR (verde) = el modelo predice "
        "subida. VENDER (rojo) = predice bajada. COMPRAR débil / VENDER débil "
        "(naranja) = predicción con poca confianza. NEUTRAL (gris) = sin tendencia "
        "clara.",
        "Precio actual: Precio de la acción en el momento en que se realizó el "
        "análisis. No es el precio en tiempo real.",
        "% predicción: Porcentaje de subida o bajada que el modelo predice para el "
        "siguiente día hábil. Positivo (+1,5 %) = se espera subida; negativo (−0,8 %) "
        "= se espera bajada.",
    ])
    body(doc,
         "Puedes filtrar la tabla haciendo clic en el icono de filtro que aparece al "
         "pasar el ratón sobre el nombre de cada columna. El botón Limpiar filtros "
         "elimina todos los filtros activos.")

    # 2.3 Distribución de señales
    heading(doc, "2.3  Distribución de señales", 2, AZUL_CLARO)
    body(doc,
         "Gráfico de tarta que resume cuántas señales de cada tipo ha generado el "
         "último análisis. Permite ver de un vistazo si el sistema detecta más "
         "oportunidades de compra o de venta en ese momento.")
    screenshot(doc, "inicio_pie.png", width=4.0, caption="Distribución de señales.")

    # 2.4 Información del análisis
    heading(doc, "2.4  Información del análisis", 2, AZUL_CLARO)
    body(doc,
         "Fecha y hora del último análisis, número total de acciones analizadas, "
         "cuántas tienen señal de compra y cuántas de venta.")

    info_box(doc, "Nota:", [
        "Los datos de las señales no se actualizan en tiempo real. Lo que ves "
        "corresponde al último análisis automático (el del día anterior si abres la "
        "aplicación por la mañana). Solo las 4 tarjetas superiores se actualizan en "
        "tiempo real conectándose a Alpaca.",
    ])

    # 2.5 Referencia de tickers
    heading(doc, "2.5  Referencia de tickers: empresas del S&P 100", 2, AZUL_CLARO)
    body(doc,
         "La siguiente tabla muestra a qué empresa corresponde cada código (ticker) "
         "que puede aparecer en la tabla de señales, junto con el sector al que "
         "pertenece.")
    col_table(doc,
        ["Ticker", "Empresa", "Sector", "País"],
        SP100_REFERENCE,
        col_widths=[0.8, 2.1, 2.1, 1.0],
    )
    p = doc.add_paragraph()
    run = p.add_run(
        "* Compañías incorporadas legalmente fuera de EE.UU. por razones fiscales, "
        "pero con sede operativa y cotización principal en bolsas americanas "
        "(NYSE/NASDAQ). A efectos prácticos se comportan como empresas "
        "estadounidenses."
    )
    run.font.size   = Pt(9)
    run.font.italic = True
    run.font.color.rgb = GRIS

    doc.add_page_break()

    # ── 3. Pestaña Análisis ───────────────────────────────────────────────────
    heading(doc, "3. Pestaña Análisis", 1, AZUL)
    body(doc,
         "La pestaña Análisis (Análisis Predictivo) es el corazón del sistema de IA: "
         "permite predecir la señal de uno o varios activos bajo demanda, revisar el "
         "detalle del modelo y del backtest, y lanzar una orden de Paper Trading "
         "manualmente, todo desde el navegador.")
    doc.add_paragraph()

    # 3.1 Filtros
    heading(doc, "3.1  Filtros de la cabecera", 2, AZUL_CLARO)
    screenshot(doc, "analisis_filtros.png", width=6.3, caption="Cabecera de filtros de la Pestaña Análisis.")
    col_table(doc,
        ["Filtro", "Descripción"],
        [
            ["Símbolos\n(combo + Agregar)",
             "Selecciona un ticker del desplegable (activos del S&P100, o 'Todos "
             "(S&P100)' para analizar los 100 de golpe) y pulsa '+ Agregar' para "
             "sumarlo como chip. Puedes añadir varios chips para analizar varios "
             "activos en una sola ejecución; cada chip lleva una '×' para quitarlo. "
             "Si no añades ningún chip, solo se analiza el símbolo del desplegable."],
            ["Periodo\n(Desde / Hasta)",
             "Rango de fechas (DD-MM-AAAA) del histórico de precios que se usará "
             "para entrenar el modelo. 'Desde' por defecto es 01-01-2022; dejar "
             "'Hasta' en blanco equivale a usar datos hasta hoy."],
            ["Umbral señal (%)",
             "Retorno mínimo que debe predecir el modelo para que la señal se "
             "considere COMPRAR o VENDER en firme (por defecto 0.5%). Entre ese "
             "umbral y el 40% del mismo, la señal se marca como 'débil' "
             "(p. ej. 'COMPRAR (débil)'); por debajo, la señal es NEUTRAL."],
            ["Ejecución\n(switch + importe $)",
             "El interruptor 'Ejecutar Compra/Venta' despliega un campo de importe "
             "en dólares por operación. Actualmente estos controles quedan "
             "reservados para una futura ejecución automática — la ejecución real "
             "de órdenes se realiza de forma manual con el panel descrito en el "
             "apartado 3.3, tras seleccionar una fila con señal COMPRAR o VENDER."],
        ],
        col_widths=[1.8, 4.7],
    )

    # 3.2 Botones
    heading(doc, "3.2  Botones \"Predecir Señal\" y \"Actualizar resultados reales\"", 2, AZUL_CLARO)
    col_table(doc,
        ["Botón", "Qué hace"],
        [
            ["Predecir Señal",
             "Ejecuta el pipeline completo de IA para cada símbolo seleccionado (o los "
             "100 del S&P100 si se eligió 'Todos'): descarga el histórico de precios "
             "(Yahoo Finance), earnings/dividendos, sentimiento de noticias y ratio "
             "put/call de opciones; calcula los indicadores técnicos; entrena (o reutiliza "
             "si ya está en caché de hoy) el ensemble XGBoost+LightGBM; genera la señal "
             "sobre la última sesión; obtiene la cotización Ask/Bid en tiempo real de "
             "Alpaca; y calcula el backtest fuera de muestra (OOS). Los resultados "
             "rellenan la tabla, y el mensaje de estado indica cuántos símbolos se "
             "analizaron correctamente y cuáles fallaron. Al hacer clic en una fila de "
             "la tabla se despliegan las tarjetas de detalle (Señal, Detalle del modelo, "
             "Factores influyentes y Backtest) y, si la señal es COMPRAR o VENDER, el "
             "panel de ejecución manual."],
            ["Actualizar resultados reales",
             "No genera predicciones nuevas: recorre el histórico de predicciones ya "
             "guardadas en la carpeta 'Analisis_Predicción' y, para aquellas cuya fecha "
             "objetivo ya pasó pero todavía no tienen resultado real registrado, descarga "
             "el precio de cierre real de Yahoo Finance y rellena el retorno real, la "
             "fecha real y si la predicción acertó o no, recalculando el porcentaje de "
             "aciertos acumulado. Se usa para auditar con el tiempo la fiabilidad real "
             "del modelo."],
        ],
        col_widths=[1.9, 4.6],
    )

    # 3.3 Tabla de resultados
    heading(doc, "3.3  Tabla de resultados", 2, AZUL_CLARO)
    body(doc,
         "Al terminar 'Predecir Señal', cada símbolo analizado aparece como una fila "
         "con estas columnas:")
    screenshot(doc, "analisis_tabla.png", width=6.3, caption="Tabla de resultados de la Pestaña Análisis.")
    col_table(doc,
        ["Columna", "Descripción"],
        [
            ["Acción",
             "El ticker del símbolo analizado (p. ej. AAPL, TSLA)."],
            ["Señal",
             "COMPRAR / VENDER / COMPRAR (débil) / VENDER (débil) / NEUTRAL, según el "
             "retorno predicho frente al umbral configurado (ver 3.1). Se muestra como "
             "una etiqueta de color: verde (COMPRAR), rojo (VENDER), naranja (señal "
             "débil) o gris (NEUTRAL)."],
            ["Ganancia esperada",
             "El retorno que el modelo predice para el próximo día hábil, en "
             "porcentaje (p. ej. +1.24% o −0.85%). Es el mismo número que determina la "
             "señal de la columna anterior."],
            ["Precio",
             "Precio de venta (ask) obtenido de Alpaca en el momento del análisis. "
             "Aparece como '—' si no se pudo obtener cotización."],
            ["Confianza",
             "Alta / Media / Baja, según la precisión direccional histórica del "
             "modelo (oos_dir_acc): Alta ≥ 54%, Media entre 51% y 54%, Baja < 51%. "
             "Cuanta más confianza, más fiable ha sido el modelo prediciendo la "
             "dirección (subida/bajada) en el pasado."],
            ["Estado",
             "'✓ OK' si el análisis se completó correctamente, o '✗' seguido del "
             "motivo si ese símbolo falló (p. ej. por falta de datos)."],
        ],
        col_widths=[1.6, 4.9],
    )

    # 3.4 Tarjetas de detalle
    heading(doc, "3.4  Tarjetas de detalle (al seleccionar un símbolo)", 2, AZUL_CLARO)
    body(doc,
         "Al hacer clic en una fila de la tabla, se despliegan cuatro tarjetas con el "
         "análisis completo de ese símbolo:")
    screenshot(doc, "analisis_detalle.png", width=6.3, caption="Tarjetas de detalle: Señal, Modelo, Factores y Backtest.")
    body(doc,
         "Muchos de estos datos usan nombres técnicos en inglés (nombres de "
         "indicadores, métricas de backtest...). Junto a cada uno de ellos hay un "
         "icono ⓘ: al pasar el ratón por encima aparece una explicación en español "
         "de qué es y qué significa.")
    screenshot(doc, "analisis_tooltip.png", width=6.3, caption="Ejemplo: tooltip en español al pasar el ratón sobre 'log_ret_1d'.")
    col_table(doc,
        ["Tarjeta", "Qué muestra"],
        [
            ["Señal de trading",
             "La señal en grande con su color, el retorno predicho, el precio Ask y "
             "Bid en tiempo real (la diferencia entre ambos es el 'spread', el coste "
             "implícito de operar) y, si hay datos, el sentimiento de las noticias "
             "recientes (de −1 muy negativo a +1 muy positivo)."],
            ["Detalle del modelo",
             "El nivel de confianza (Alta/Media/Baja) y la precisión direccional del "
             "modelo (% de veces que acertó si el precio subía o bajaba en el "
             "histórico de validación), el error medio de predicción (OOS MAE) y el "
             "número de muestras (días históricos) usadas para entrenar."],
            ["Factores influyentes",
             "Los 6 indicadores técnicos con más peso en la predicción de ese "
             "símbolo concreto (RSI, MACD, medias móviles, volatilidad, etc.), con "
             "una barra que representa su importancia relativa. Ayuda a entender en "
             "qué se ha basado el modelo para generar la señal."],
            ["Backtest",
             "Resultado de simular la estrategia sobre datos históricos que el "
             "modelo no vio durante el entrenamiento: número de operaciones "
             "(Trades), % de operaciones ganadoras (Win rate), rentabilidad ajustada "
             "al riesgo (Sharpe), máxima caída desde un máximo (Max DD), rentabilidad "
             "anualizada (CAGR), rentabilidad extra sobre comprar-y-mantener (Alpha) "
             "y el retorno de comprar-y-mantener en el mismo periodo (B&H return)."],
        ],
        col_widths=[1.6, 4.9],
    )
    info_box(doc, "Nota:", [
        "Si la señal seleccionada es COMPRAR o VENDER, además de las cuatro "
        "tarjetas se despliega el panel de ejecución manual (ver 3.6). Con señal "
        "NEUTRAL, ese panel no aparece.",
    ])

    # 3.5 Glosario de variables
    heading(doc, "3.5  Glosario de variables (contenido de los tooltips)", 2, AZUL_CLARO)
    body(doc,
         "Referencia completa de los términos técnicos que pueden aparecer en la "
         "tarjeta 'Factores influyentes' (nombres de indicadores) y en la tarjeta "
         "'Backtest' (métricas de rentabilidad y riesgo). Es el mismo texto que "
         "muestra cada tooltip ⓘ en el dashboard.")

    body(doc, "Indicadores técnicos (tarjeta Factores influyentes):", bold=True)
    col_table(doc,
        ["Variable", "Qué es"],
        [
            ["log_ret_1d / 5d / 20d",  "Retorno logarítmico del último día / 5 días / 20 días (~1 mes)."],
            ["sma20 / sma50",          "Media móvil simple de 20 y de 50 días."],
            ["sma_ratio",              "SMA20 ÷ SMA50: por encima de 1, tendencia alcista; por debajo, bajista."],
            ["price_sma20",            "Precio actual dividido entre su media móvil de 20 días."],
            ["macd",                   "Diferencia entre las medias móviles exponenciales de 12 y 26 días."],
            ["macd_signal",            "Línea de señal del MACD (media exponencial de 9 días del propio MACD)."],
            ["macd_hist",              "Histograma MACD: diferencia entre el MACD y su línea de señal."],
            ["rsi",                    "Índice de fuerza relativa (14 días): >70 sobrecompra, <30 sobreventa."],
            ["bb_upper / bb_lower / bb_mid", "Bandas de Bollinger superior, inferior y media (20 días, ±2σ)."],
            ["bb_bwidth",              "Ancho de las Bandas de Bollinger: mide la volatilidad reciente."],
            ["bb_pct",                 "Posición del precio dentro de las bandas (0 = inferior, 1 = superior)."],
            ["atr",                    "Rango medio real (14 días): volatilidad media del precio."],
            ["vol_sma20",              "Media móvil del volumen negociado en 20 días."],
            ["vol_ratio",              "Volumen actual ÷ su media de 20 días; alto = actividad inusual."],
            ["hl_range",               "Rango intradía (máximo − mínimo) dividido entre el cierre."],
            ["close",                  "Precio de cierre de la última sesión."],
            ["days_to_earnings",       "Días que faltan hasta la próxima publicación de resultados."],
            ["is_earnings_week",       "Si la publicación de resultados cae en los próximos 5 días."],
            ["days_to_exdiv",          "Días que faltan hasta la próxima fecha ex-dividendo."],
            ["is_pre_exdiv",           "Si la fecha ex-dividendo cae en los próximos 5 días."],
            ["vix",                    "Nivel del índice VIX: volatilidad esperada del mercado ('índice del miedo')."],
            ["vix_chg_5d",             "Variación del VIX en los últimos 5 días."],
            ["rel_ret_5d / rel_ret_20d", "Retorno del activo en 5 / 20 días, comparado con el S&P 500 (SPY)."],
        ],
        col_widths=[2.0, 4.5],
    )

    body(doc, "Métricas de rentabilidad y riesgo (tarjeta Backtest):", bold=True)
    col_table(doc,
        ["Métrica", "Qué es"],
        [
            ["Win rate",   "Porcentaje de operaciones del backtest que resultaron ganadoras."],
            ["Sharpe",     "Ratio de Sharpe: rentabilidad obtenida por unidad de riesgo asumido. Más alto es mejor."],
            ["Max DD",     "Máxima caída (drawdown): la mayor pérdida desde un máximo hasta el siguiente mínimo."],
            ["CAGR",       "Tasa de crecimiento anual compuesta: rentabilidad media anualizada de la estrategia."],
            ["Alpha",      "Rentabilidad extra de la estrategia frente a comprar y mantener (Buy & Hold)."],
            ["B&H return", "Buy & Hold: retorno de comprar el activo al inicio y mantenerlo, sin operar."],
            ["OOS MAE",    "Error absoluto medio fuera de muestra: cuánto se equivoca el modelo en promedio, "
                           "medido con datos que no usó para entrenar (tarjeta Detalle del modelo)."],
        ],
        col_widths=[1.6, 4.9],
    )

    # 3.5 Panel de ejecución manual
    heading(doc, "3.6  Panel \"Ejecutar Orden Manual\"", 2, AZUL_CLARO)
    body(doc,
         "Al seleccionar en la tabla una fila cuya señal sea COMPRAR o VENDER (las "
         "señales NEUTRAL no muestran este panel), aparece un panel inferior con el "
         "símbolo, la señal, el retorno predicho y el precio, un campo de importe en "
         "dólares y un botón 'Comprar <símbolo>' / 'Vender <símbolo>'. Al pulsarlo se "
         "envía la orden a Alpaca en modo Paper Trading, pero antes se aplican varios "
         "filtros de seguridad: se descarta la orden si la precisión direccional del "
         "modelo (Dir. Acc.) está por debajo del mínimo exigido, si ya existe una orden "
         "abierta para ese símbolo, o si hay algún problema al consultar la cuenta. El "
         "resultado (orden ejecutada, omitida o con error) se muestra justo debajo del "
         "botón.")
    screenshot(doc, "analisis_ejecucion.png", width=6.3, caption="Panel de ejecución manual, con señal COMPRAR.")

    doc.add_page_break()

    # ── 4. Pestaña Precio ─────────────────────────────────────────────────────
    heading(doc, "4. Pestaña Precio", 1, AZUL)
    body(doc,
         "La pestaña Precio muestra la evolución histórica de un activo mediante un "
         "gráfico de velas (candlestick) interactivo, con sus medias móviles y el "
         "volumen negociado, para inspeccionar visualmente cualquier símbolo del "
         "S&P 100 sin necesidad de lanzar un análisis de IA.")
    doc.add_paragraph()

    # 4.1 Controles
    heading(doc, "4.1  Controles", 2, AZUL_CLARO)
    screenshot(doc, "precio_controles.png", width=6.3, caption="Controles de la Pestaña Precio.")
    col_table(doc,
        ["Control", "Descripción"],
        [
            ["Símbolo",
             "Desplegable con los activos del S&P100. Al cambiarlo, el gráfico se "
             "actualiza automáticamente con los datos del nuevo símbolo."],
            ["Intervalo",
             "Tamaño de cada vela: Diario, 1 Hora o 15 Min. Los intervalos "
             "intradía (1 Hora, 15 Min) muestran menos historial hacia atrás, ya "
             "que Yahoo Finance solo conserva datos intradía recientes."],
            ["Periodo",
             "Ventana de tiempo que se muestra hacia atrás desde hoy: 1 mes, 3 "
             "meses, 6 meses, 1 año o 2 años."],
        ],
        col_widths=[1.6, 4.9],
    )

    body(doc, "¿Qué significa cada Intervalo?", bold=True)
    body(doc,
         "El intervalo define qué periodo de tiempo resume cada vela del gráfico: "
         "cuanto más pequeño, más detalle a corto plazo, pero menos historial "
         "disponible hacia atrás.")
    col_table(doc,
        ["Intervalo", "Qué muestra cada vela", "Historial disponible"],
        [
            ["Diario",
             "La sesión bursátil completa de un día (apertura, máximo, mínimo y "
             "cierre de esa jornada).",
             "Sin límite práctico: puedes ver años de historial (1 año, 2 años...)."],
            ["1 Hora",
             "Lo ocurrido en una hora de negociación dentro de la sesión bursátil.",
             "Hasta unos 2 años hacia atrás."],
            ["15 Min",
             "Lo ocurrido en un tramo de 15 minutos dentro de la sesión.",
             "Solo los últimos ~60 días (límite que impone Yahoo Finance para "
             "datos tan granulares). Si eliges un Periodo más largo con este "
             "intervalo, el gráfico puede mostrar el aviso 'Sin datos'."],
        ],
        col_widths=[1.2, 3.0, 2.3],
    )

    body(doc, "¿Qué significa cada Periodo?", bold=True)
    body(doc,
         "El periodo define cuánto tiempo hacia atrás desde hoy se representa en "
         "el gráfico, manteniendo el intervalo elegido. Por ejemplo, 'Diario' + "
         "'6 meses' dibuja una vela por cada día de los últimos 6 meses; '1 Hora' "
         "+ '1 mes' dibuja una vela por cada hora negociada en el último mes. "
         "Cuanto mayor el periodo, más contexto histórico se ve, pero cada vela "
         "individual ocupa menos espacio horizontal en pantalla.")

    # 4.2 Gráfico de velas
    heading(doc, "4.2  Gráfico de velas", 2, AZUL_CLARO)
    body(doc,
         "Cada vela representa un periodo (un día, una hora o 15 minutos, según el "
         "intervalo elegido): vela verde si el cierre quedó por encima de la "
         "apertura (sesión alcista), vela roja si quedó por debajo (sesión "
         "bajista). La línea vertical de cada vela (mecha) marca el máximo y el "
         "mínimo alcanzados en ese periodo.")
    screenshot(doc, "precio_velas.png", width=6.3, caption="Gráfico de velas con medias móviles MA20 y MA50.")

    body(doc, "Los ejes de coordenadas:", bold=True)
    bullet_list(doc, [
        "Eje X (horizontal): el tiempo. Cada vela ocupa una posición fija según "
        "su fecha (o fecha y hora, en los intervalos intradía); las velas más a "
        "la derecha son las más recientes.",
        "Eje Y (vertical, a la derecha del gráfico): el precio del activo en "
        "dólares. Cuanto más arriba está dibujada una vela, mayor era el precio "
        "del activo en ese periodo.",
    ])

    body(doc, "Qué representa cada vela (variables OHLC):", bold=True)
    body(doc,
         "La posición y el tamaño de cada vela codifican cuatro precios de ese "
         "periodo, conocidos como OHLC (Open-High-Low-Close):")
    bullet_list(doc, [
        "Open (apertura): precio al que empezó a cotizar el activo en ese "
        "periodo. Es uno de los dos extremos del cuerpo (rectángulo) de la vela.",
        "Close (cierre): precio al que terminó cotizando ese periodo. Es el otro "
        "extremo del cuerpo. Si el cierre queda por encima de la apertura, el "
        "cuerpo se pinta verde (subió); si queda por debajo, rojo (bajó).",
        "High (máximo): el precio más alto alcanzado durante el periodo. Marca "
        "el extremo superior de la mecha (la línea fina que sobresale del "
        "cuerpo).",
        "Low (mínimo): el precio más bajo alcanzado durante el periodo. Marca el "
        "extremo inferior de la mecha.",
    ])
    body(doc,
         "En resumen: el cuerpo de la vela (la parte ancha) va de Open a Close, "
         "y las mechas (las líneas finas de arriba y abajo) llegan hasta el High "
         "y el Low. Una mecha larga indica que el precio osciló mucho durante "
         "ese periodo antes de asentarse en su cierre.")

    body(doc, "Qué significa el tamaño de la vela:", bold=True)
    bullet_list(doc, [
        "Cuerpo grande (mucha distancia entre Open y Close): movimiento fuerte "
        "y decidido en esa sesión, con mucha diferencia entre el precio de "
        "apertura y el de cierre. Cuanto más grande el cuerpo, más contundente "
        "fue la subida (verde) o la bajada (roja).",
        "Cuerpo pequeño o casi inexistente (Open y Close muy parecidos): "
        "indecisión del mercado en ese periodo — compradores y vendedores se "
        "compensaron y el precio terminó casi donde empezó, aunque haya podido "
        "moverse mucho por el camino (mechas largas). Suele preceder a un "
        "cambio de tendencia.",
        "Mechas largas con cuerpo pequeño: el precio llegó a moverse mucho "
        "durante el periodo (hasta el High o el Low) pero acabó volviendo cerca "
        "de donde empezó, señal de que el movimiento encontró resistencia.",
        "Cuerpo grande sin apenas mechas: el precio se movió en una sola "
        "dirección de forma sostenida durante todo el periodo, sin apenas "
        "retrocesos.",
    ])
    screenshot(doc, "precio_velas_formas.png", width=6.3,
               caption="Las 4 formas anteriores, para identificarlas visualmente.")

    screenshot(doc, "precio_velas_hover.png", width=6.3,
               caption="Al pasar el ratón sobre una vela aparece un tooltip en español con sus 4 valores.")
    body(doc,
         "Pasando el ratón sobre cualquier vela aparece un recuadro (tooltip) con "
         "la fecha exacta y sus cuatro valores, ya traducidos: Apertura, Máximo, "
         "Mínimo y Cierre, además de una flecha ▲ (subió) o ▼ (bajó) que indica "
         "el sentido de esa sesión.")

    body(doc, "Sobre las velas se dibujan además dos medias móviles de referencia:")
    bullet_list(doc, [
        "MA20 (azul): media móvil de los últimos 20 periodos. Reacciona rápido a "
        "los cambios de precio.",
        "MA50 (naranja): media móvil de los últimos 50 periodos. Más suave, "
        "refleja la tendencia de fondo.",
        "Cuando la MA20 está por encima de la MA50, suele interpretarse como "
        "tendencia alcista a corto plazo; por debajo, como tendencia bajista.",
    ])
    info_box(doc, "Herramientas del gráfico:", [
        "La barra de iconos de la esquina superior derecha permite hacer zoom, "
        "desplazarte por el histórico, descargar la imagen o resetear la vista.",
        "Puedes arrastrar sobre el gráfico para hacer zoom en un rango concreto, "
        "y usar la rueda del ratón para acercar/alejar.",
        "Haciendo clic sobre 'AAPL', 'MA20' o 'MA50' en la leyenda puedes "
        "ocultar o mostrar esa serie, para ver el gráfico más despejado.",
    ])

    # 4.3 Gráfico de volumen
    heading(doc, "4.3  Gráfico de volumen", 2, AZUL_CLARO)
    body(doc,
         "Debajo del gráfico de velas, un gráfico de barras muestra el volumen "
         "(número de acciones negociadas) en cada periodo, sincronizado con el "
         "mismo eje de fechas del gráfico de velas: cada barra queda justo "
         "debajo de la vela a la que corresponde.")
    screenshot(doc, "precio_volumen.png", width=6.3, caption="Gráfico de volumen negociado.")

    body(doc, "Los ejes de coordenadas:", bold=True)
    bullet_list(doc, [
        "Eje X (horizontal): el mismo eje de tiempo que el gráfico de velas de "
        "arriba (comparten fechas, aunque este gráfico no muestra las etiquetas "
        "de fecha para ahorrar espacio).",
        "Eje Y (vertical, a la derecha): el número de acciones negociadas en ese "
        "periodo, abreviado (p. ej. '100M' = 100 millones de acciones).",
    ])

    body(doc, "Qué significan las barras y sus colores:", bold=True)
    bullet_list(doc, [
        "La altura de cada barra es el volumen negociado en ese periodo: cuanto "
        "más alta, más acciones cambiaron de manos.",
        "Cada barra hereda el color de su vela correspondiente: verde si esa "
        "sesión cerró en subida (close > open), roja si cerró en bajada.",
        "Los picos de volumen suelen coincidir con noticias relevantes "
        "(resultados, anuncios) y ayudan a confirmar si un movimiento de precio "
        "tiene respaldo (mucho volumen) o es poco significativo (volumen bajo).",
    ])

    screenshot(doc, "precio_volumen_hover.png", width=6.3,
               caption="Tooltip del gráfico de volumen: fecha y número de acciones negociadas.")
    body(doc,
         "Pasando el ratón sobre cualquier barra aparece un tooltip con la fecha "
         "de ese periodo y el volumen exacto negociado (por ejemplo, '(Jun 26, "
         "2026, 260M)' significa 260 millones de acciones negociadas ese día).")

    doc.add_page_break()

    # ── 5. Pestaña Cartera ────────────────────────────────────────────────────
    heading(doc, "5. Pestaña Cartera", 1, AZUL)
    body(doc,
         "La pestaña Cartera muestra el estado de tu cuenta de Paper Trading en "
         "Alpaca: cuánto valen tus posiciones abiertas, cuánto ganas o pierdes "
         "con ellas, el detalle de cada una y cómo ha evolucionado el valor total "
         "de la cuenta en el último mes. Se actualiza automáticamente cada 3 "
         "minutos.")
    doc.add_paragraph()

    # 5.1 Tarjetas de resumen
    heading(doc, "5.1  Tarjetas de resumen", 2, AZUL_CLARO)
    screenshot(doc, "cartera_kpis.png", width=6.3, caption="Tarjetas de resumen de la Pestaña Cartera.")
    col_table(doc,
        ["Tarjeta", "Qué significa"],
        [
            ["Valor de las posiciones",
             "Cuánto valen HOY, en total, las acciones que tienes compradas "
             "(cantidad × precio actual de cada una). No incluye el efectivo "
             "que tengas sin invertir — solo lo que está metido en bolsa."],
            ["Ganancia / Pérdida no realizada",
             "Cuánto ganarías o perderías si vendieras todo ahora mismo: la "
             "diferencia entre lo que pagaste por cada acción (precio de "
             "entrada) y lo que vale hoy. Se llama 'no realizada' porque "
             "todavía no has vendido — el número sube y baja con el precio en "
             "tiempo real, y solo se convierte en ganancia o pérdida real "
             "cuando cierras (vendes) la posición. Verde si es positiva, rojo "
             "si es negativa."],
            ["Posiciones abiertas",
             "El número de acciones distintas que tienes compradas ahora mismo "
             "(por ejemplo, si tienes AAPL, TSLA y NVDA, aquí pone 3)."],
        ],
        col_widths=[2.0, 4.5],
    )
    screenshot(doc, "cartera_kpi_tooltip.png", width=6.3,
               caption="Cada tarjeta tiene un icono ⓘ con la misma explicación, por si la necesitas sin abrir el manual.")

    # 5.2 Tabla de posiciones abiertas
    heading(doc, "5.2  Tabla de posiciones abiertas", 2, AZUL_CLARO)
    body(doc,
         "Detalla, acción por acción, todo lo que tienes comprado. Mismo estilo "
         "de tabla que en la Pestaña Análisis: cabecera con filtros, columnas "
         "ordenables y paginación. Además, cada cabecera con nombre técnico "
         "tiene su propio tooltip: pasa el ratón por encima del título de la "
         "columna y aparece la explicación, sin necesidad de abrir este manual.")
    screenshot(doc, "cartera_tabla.png", width=6.3, caption="Tabla de posiciones abiertas.")
    col_table(doc,
        ["Columna", "Qué significa"],
        [
            ["Símbolo",
             "El ticker de la acción que tienes comprada (p. ej. AAPL)."],
            ["Fecha compra",
             "Fecha de la última compra ejecutada de ese símbolo (si compraste "
             "varias veces, se muestra la más reciente)."],
            ["Cantidad",
             "Número de acciones que posees de ese símbolo."],
            ["Precio compra",
             "Precio de UNA acción: la media a la que compraste (si "
             "compraste en varias veces, es la media ponderada). No es el "
             "total que gastaste — para eso está la columna 'Total "
             "invertido'. No cambia con el mercado."],
            ["Precio actual",
             "Precio de UNA acción ahora mismo, en vivo. Ojo: esto NO es el "
             "valor de tu posición, es solo la cotización por acción."],
            ["Total invertido",
             "Lo que gastaste EN TOTAL comprando ese símbolo: Cantidad × "
             "Precio compra. Es un importe fijo — no cambia aunque el precio "
             "de mercado suba o baje, porque es lo que realmente pagaste."],
            ["Valor de la posición",
             "Cuánto vale HOY toda esa posición en conjunto: Cantidad × Precio "
             "actual. Compara esta columna con 'Total invertido': si es mayor, "
             "vas ganando; si es menor, vas perdiendo — es la forma más "
             "directa de ver de un vistazo si estás ganando o perdiendo hoy "
             "con ese símbolo."],
            ["Ganancia / Pérdida",
             "La diferencia exacta entre las dos columnas anteriores (Valor "
             "de la posición − Total invertido): lo que ganarías o perderías "
             "si vendieras esa posición ahora mismo. Todavía no es dinero "
             "real hasta que vendas. Verde si vender ahora te daría "
             "ganancia, rojo si te daría pérdida."],
        ],
        col_widths=[1.7, 4.8],
    )

    # 5.3 Evolución del valor de la cuenta
    heading(doc, "5.3  Evolución del valor de la cuenta", 2, AZUL_CLARO)
    body(doc,
         "Gráfico de línea con el valor total de la cuenta (efectivo disponible "
         "más el valor de todas las posiciones) día a día durante el último "
         "mes — a diferencia de las tarjetas de arriba, aquí sí se cuenta el "
         "efectivo. Sirve para ver de un vistazo si la cuenta en conjunto está "
         "creciendo o encogiendo con el paso de los días, más allá de las "
         "posiciones abiertas en este momento.")
    screenshot(doc, "cartera_equity.png", width=6.3, caption="Evolución del valor total de la cuenta (último mes).")
    info_box(doc, "Nota:", [
        "El eje Y no siempre empieza en $0: se ajusta automáticamente al rango "
        "de valores del último mes para que se aprecien bien las subidas y "
        "bajadas, aunque sean pequeñas en proporción al total de la cuenta.",
        "Si la cuenta es nueva o no ha habido movimientos, este gráfico puede "
        "mostrar una línea plana o el aviso 'Sin historial disponible'.",
    ])

    doc.add_page_break()

    # ── 6. Pestaña Historial ──────────────────────────────────────────────────
    heading(doc, "6. Pestaña Historial", 1, AZUL)
    body(doc,
         "La pestaña Historial es la 'memoria' completa de todas las señales "
         "generadas a lo largo del tiempo: tanto las del escaneo automático "
         "diario del S&P100 como las que tú mismo lanzas manualmente desde la "
         "Pestaña Análisis con el botón 'Predecir Señal'. A diferencia de la "
         "tabla de Análisis (que solo muestra el resultado del análisis que "
         "acabas de lanzar), aquí se acumulan todos los registros — es el "
         "archivo scan_log.csv, que va creciendo con cada escaneo.")
    doc.add_paragraph()

    # 6.1 Filtros
    heading(doc, "6.1  Filtros de la cabecera", 2, AZUL_CLARO)
    screenshot(doc, "historial_filtros.png", width=6.3, caption="Filtros de la Pestaña Historial.")
    col_table(doc,
        ["Filtro", "Descripción"],
        [
            ["Filtrar por señal",
             "Todas / COMPRAR / VENDER / Débiles. Muestra solo las señales "
             "fuertes de compra, de venta, o las marcadas como 'débil' "
             "(COMPRAR (débil) / VENDER (débil))."],
            ["Buscar símbolo",
             "Campo de texto libre (p. ej. 'AAPL') que filtra la tabla por "
             "coincidencia parcial del ticker."],
            ["Actualizar",
             "Vuelve a leer el archivo de registro desde disco, por si se ha "
             "lanzado un escaneo nuevo mientras tenías la pestaña abierta."],
        ],
        col_widths=[1.8, 4.7],
    )

    # 6.2 Tabla
    heading(doc, "6.2  Tabla de registros", 2, AZUL_CLARO)
    body(doc,
         "Cada fila es una señal generada en un momento concreto. Con cientos "
         "de registros acumulados, la tabla usa paginación (50 filas por "
         "página) y cada columna se puede ordenar y filtrar, igual que en las "
         "demás tablas del dashboard.")
    screenshot(doc, "historial_tabla.png", width=6.3, caption="Tabla de registros de la Pestaña Historial.")
    col_table(doc,
        ["Columna", "Qué significa"],
        [
            ["Fecha/Hora",
             "Cuándo se generó esa señal: la fecha y hora exactas de ese "
             "escaneo o análisis concreto."],
            ["Símbolo",
             "El ticker analizado."],
            ["Señal",
             "COMPRAR/VENDER/débil/NEUTRAL, coloreada igual que en las demás "
             "pestañas (verde/rojo/naranja/gris)."],
            ["Pred. Ret. %",
             "El retorno % que predijo el modelo para el día siguiente, en "
             "el momento de ese escaneo."],
            ["Dir. Acc. %",
             "Precisión direccional del modelo en ese momento — el mismo dato "
             "que 'Confianza' en la Pestaña Análisis, aquí en número exacto "
             "en vez de Alta/Media/Baja."],
            ["Ask",
             "Precio de venta (cotización) del activo en el momento del "
             "escaneo. El registro también guarda el precio 'Bid', aunque "
             "esa columna no se muestra en esta tabla."],
            ["Sentiment",
             "Sentimiento de las noticias recientes en ese momento, de −1 "
             "(muy negativo) a +1 (muy positivo)."],
            ["P/C Ratio",
             "Ratio Put/Call: interés abierto en opciones 'put' dividido "
             "entre 'call'. Por encima de 1 indica más cobertura bajista "
             "(más puts que calls); por debajo de 1, más apuesta alcista."],
            ["Modelo",
             "Qué modelo de IA estaba activo en Configuración cuando se "
             "generó esa señal (p. ej. 'xgb_lgb_ensemble'). Las filas "
             "anteriores a que se empezara a registrar este dato aparecen en "
             "blanco."],
            ["Fuente de datos",
             "De dónde venían los precios históricos usados para entrenar y "
             "predecir en ese momento (p. ej. 'yahoo'). Igual que 'Modelo', "
             "las filas antiguas aparecen en blanco."],
        ],
        col_widths=[1.6, 4.9],
    )
    info_box(doc, "Para qué sirven 'Modelo' y 'Fuente de datos':", [
        "Si en el futuro cambias de modelo o de fuente de datos en "
        "Configuración, estas dos columnas te permiten comparar cómo se "
        "comportó cada combinación a lo largo del tiempo, filtrando o "
        "revisando el historial por esos valores.",
    ])

    doc.add_page_break()

    # ── 7. Pestaña pendiente de documentar ────────────────────────────────────
    heading(doc, "7. Pestaña Comparación", 1, AZUL)

    doc.add_page_break()

    # ── 8. Anexo: cómo se rellenan los ficheros de datos ────────────────────
    heading(doc, "8. Anexo: cómo se rellenan los ficheros de datos", 1, AZUL)
    body(doc,
         "AlgoTrader tiene dos interfaces que comparten la misma capa de datos "
         "(carpeta 'src/'): el dashboard web (este manual) y una app de "
         "escritorio PyQt6 más antigua. Ambas leen y escriben sobre los mismos "
         "ficheros, pero no todas las acciones están disponibles en las dos. "
         "Esta tabla aclara, ficha por ficha, desde qué botón concreto se "
         "rellena cada uno y si ese origen está en la web o solo en la app de "
         "escritorio.")

    body(doc, "8.1  Ficheros que sí rellena la web", bold=True, color=AZUL_CLARO)
    col_table(doc,
        ["Fichero", "Botón / origen en la web"],
        [
            ["scan_log.csv",
             "Inicio → 'Lanzar análisis ahora' (lanza scan_sp100.py) y "
             "Análisis → 'Predecir Señal'. Ambos llaman a append_scan_log(); "
             "solo guarda señales que no sean NEUTRAL."],
            ["pending_signals.json",
             "Solo el scan scan_sp100.py (automático por Task Scheduler o "
             "manual vía 'Lanzar análisis ahora'). Lo lee la tabla de señales "
             "de Inicio."],
            ["scan_status.json",
             "Inicio → 'Lanzar análisis ahora'. Estado idle/running/done/"
             "error, escrito por web/scan_runner.py mientras dura el "
             "subproceso del scan."],
            ["settings.json",
             "Configuración → 'Guardar'."],
            ["data_cache/*.parquet",
             "Cualquier análisis (scan automático o 'Predecir Señal'): "
             "caché de precios históricos por fuente de datos."],
            ["models/*.joblib",
             "Cualquier análisis: caché de los modelos de IA ya entrenados "
             "por símbolo."],
        ],
        col_widths=[1.9, 4.6],
    )

    body(doc, "8.2  Ficheros que la web solo lee (los rellena la app de escritorio)",
         bold=True, color=AZUL_CLARO)
    col_table(doc,
        ["Fichero", "Quién lo rellena de verdad"],
        [
            ["predictions_log.csv",
             "Solo la app de escritorio PyQt6 (main_window.py). La pestaña "
             "Comparación de la web únicamente lo lee con get_predictions_log(); "
             "el botón 'Predecir Señal' de la web no escribe en este fichero."],
            ["orders_log.csv",
             "Solo la app de escritorio PyQt6. El panel 'Ejecutar Orden "
             "Manual' de la web envía la orden real a Alpaca, pero no la "
             "registra en este CSV — la web solo lo lee con get_orders_log()."],
            ["Analisis_Predicción/*.xlsx",
             "Solo la app de escritorio PyQt6, vía save_real_data() y "
             "save_prediction(). El botón web 'Actualizar resultados reales' "
             "solo actualiza filas ya existentes (update_actuals()); si solo "
             "usas la web, nunca se crean filas nuevas aquí."],
        ],
        col_widths=[1.9, 4.6],
    )

    body(doc, "8.3  Ficheros ajenos al dashboard web", bold=True, color=AZUL_CLARO)
    col_table(doc,
        ["Fichero", "Origen real"],
        [
            ["scan_log_console.txt",
             "run_scan.bat (Task Scheduler), que redirige la salida de "
             "consola con '>>'. El scan lanzado desde la web usa "
             "subprocess.DEVNULL, así que no escribe aquí."],
            ["telegram_handler_state.json",
             "telegram_handler.py, un proceso de Telegram independiente "
             "(run_handler.bat) sin relación con la web."],
        ],
        col_widths=[1.9, 4.6],
    )

    info_box(doc, "En resumen:", [
        "Si se usa solo la web (sin abrir nunca la app de escritorio), "
        "predictions_log.csv, orders_log.csv y la carpeta "
        "Analisis_Predicción se quedan vacíos o congelados.",
        "Eso significa que la pestaña Comparación y el histórico de "
        "aciertos por símbolo dependen hoy de datos que solo genera la app "
        "de escritorio, no el dashboard web.",
    ])

    doc.save(str(OUTPUT))
    print(f"Manual guardado en: {OUTPUT}")


if __name__ == "__main__":
    build()
