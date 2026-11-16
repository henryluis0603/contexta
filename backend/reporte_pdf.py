"""Informe en PDF compuesto con LaTeX, para adjuntarlo al papel de trabajo de auditoría.

`informe_latex` arma el .tex (siempre funciona) y `compilar_pdf` lo compila con el primer motor que encuentre
(tectonic, pdflatex o xelatex). En Streamlit Community Cloud, TeX Live se instala con packages.txt.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from ai.rag import sin_hechos
from backend.models import (CATEGORIAS_ALERTA, CRITERIOS_SBS, DIMENSIONES, NOMBRE_CRIT, NOMBRE_DIM,
                            NOMBRE_FICHA, NOMBRE_SENAL, NORMA_ALERTAS, NORMA_CPP, NORMA_GRUPO)

COLOR_REL = {"alta": "rojo", "media": "ambar", "baja": "gris"}
RANGO = {"alta": 0, "media": 1, "baja": 2}
NOTA_VACIAS = ("No equivale a una constancia negativa: confírmalo en las fuentes oficiales y en las listas internas "
               "del banco.")
NOTA_SIN_GRUPO = ("No se halló evidencia pública de que la empresa pertenezca a un grupo económico. Verifícalo con la "
                  "información de vinculación del expediente y del RCC.")
COLOR_SENAL = {"favorable": "verde", "neutral": "ambar", "desfavorable": "rojo", "sin_evidencia": "gris"}
FLECHA = {"positivo": r"\textcolor{verde}{$\blacktriangle$}", "negativo": r"\textcolor{rojo}{$\blacktriangledown$}",
          "neutral": r"\textcolor{gris}{$\bullet$}"}

_ESCAPES = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
            "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
            "≈": "aprox.", "→": "->", "≥": ">=", "≤": "<=", "•": "-", "\u00a0": " "}
_PERMITIDOS = set("–—“”‘’…€›")


def esc(texto: str) -> str:
    """Escapa caracteres especiales de LaTeX y descarta los que pdflatex no sabe dibujar (emojis, símbolos)."""
    out = []
    for c in str(texto):
        if c in _ESCAPES:
            out.append(_ESCAPES[c])
        elif ord(c) < 256 or c in _PERMITIDOS:
            out.append(c)
    return "".join(out)


def _sector(datos: dict) -> str:
    return " › ".join(x for x in (datos["sector"], datos.get("subsector")) if x)


def _url(u: str) -> str:
    return u.replace("\\", "").replace("%", r"\%").replace("#", r"\#").replace("&", r"\&")


def _citas(fuentes: list[str], etiquetas: dict) -> str:
    return " ".join(rf"\href{{{_url(etiquetas[f].url)}}}{{\textcolor{{enlace}}{{[{f}]}}}}"
                    for f in fuentes if f in etiquetas)


def _items(hallazgos, etiquetas, prefijo=lambda h: "") -> str:
    if not hallazgos:
        return r"\textit{Sin factores con fuente suficiente.}" + "\n"
    filas = [rf"  \item[{FLECHA[h.impacto]}] {prefijo(h)}{esc(h.afirmacion)} {_citas(h.fuentes, etiquetas)}"
             + (rf"\\ {{\small\textcolor{{gris}}{{\textit{{Implicancia:}} {esc(h.implicancia)}}}}}"
                if getattr(h, "implicancia", "") else "")
             for h in hallazgos]
    return "\\begin{itemize}\n" + "\n".join(filas) + "\n\\end{itemize}\n"


def _senal(s: str) -> str:
    return rf"\textcolor{{{COLOR_SENAL[s]}}}{{\textbf{{{NOMBRE_SENAL[s]}}}}}"


def _alertas_tex(inf, et) -> str:
    al = sorted(inf.senales_y_alertas, key=lambda a: RANGO[a.relevancia])
    partes = []
    for c, nombre in CATEGORIAS_ALERTA.items():
        xs = [a for a in al if a.categoria == c]
        if not xs:
            continue
        filas = [rf"  \item[\textcolor{{{COLOR_REL[a.relevancia]}}}{{\textbf{{\scriptsize {a.relevancia.upper()}}}}}] "
                 rf"\textbf{{{esc(a.fecha_del_hecho)}.}} {esc(a.afirmacion)} {_citas(a.fuentes, et)}"
                 + (rf"\\ {{\small\textcolor{{gris}}{{\textit{{Implicancia:}} {esc(a.implicancia)}}}}}" if a.implicancia else "")
                 for a in xs]
        partes.append(rf"\paragraph{{{esc(nombre)}.}}" + "\n\\begin{itemize}\n"
                      + "\n".join(filas) + "\n\\end{itemize}\n")
    vacias = [n for c, n in CATEGORIAS_ALERTA.items() if not any(a.categoria == c for a in al)]
    if vacias:
        partes.append(rf"{{\small\textcolor{{gris}}{{\textbf{{Sin hallazgos en las fuentes consultadas:}} "
                      rf"{esc('; '.join(vacias))}. {esc(NOTA_VACIAS)}}}}}" + "\n")
    return "\n".join(partes) or r"\textit{No se hallaron señales con fuente.}"


def _grupo_tex(inf, et) -> str:
    g = inf.grupo_economico
    if g.pertenece != "si":
        return r"\textit{" + esc(NOTA_SIN_GRUPO) + "}\n"
    out = (rf"\textbf{{{esc(g.nombre_del_grupo)}}}" + "\n\n" if g.nombre_del_grupo else "")
    out += (rf"\textit{{{esc(g.sintesis)}}}" + "\n" if g.sintesis else "")
    con = [v for v in g.vinculadas if not sin_hechos(v)]
    sin = [v for v in g.vinculadas if sin_hechos(v)]
    if con:
        out += "\\begin{itemize}\n" + "\n".join(
            rf"  \item[{FLECHA[v.impacto]}] \textbf{{{esc(v.empresa)}}} ({esc(v.relacion)}): {esc(v.situacion)} "
            rf"{_citas(v.fuentes, et)}" for v in con) + "\n\\end{itemize}\n"
    if sin:
        out += (rf"{{\small\textcolor{{gris}}{{\textbf{{Otras vinculadas sin hechos relevantes en la evidencia:}} "
                rf"{esc(', '.join(v.empresa for v in sin)).rstrip('.')}.}}}} "
                + _citas(sorted({f for v in sin for f in v.fuentes}), et) + "\n\n")
    if g.hallazgos:
        out += _items(g.hallazgos, et)
    return out


def informe_latex(datos: dict, res: dict) -> str:
    inf, et = res["informe"], res["etiquetas"]
    dims = {d.nombre: d for d in inf.dimensiones}
    u = res["uso"]

    tabla_dims = " \\\\\n".join(
        rf"{NOMBRE_DIM[k]} & {_senal(dims[k].senal if k in dims else 'sin_evidencia')}" for k in DIMENSIONES)

    sbs = []
    for crit in CRITERIOS_SBS:
        hs = [h for h in inf.insumos_clasificacion_sbs if h.criterio == crit]
        if hs:
            sbs.append(rf"\paragraph{{{NOMBRE_CRIT[crit]}.}} \textcolor{{gris}}{{{esc(CRITERIOS_SBS[crit])}}}" + "\n"
                       + _items(hs, et))
    sbs_txt = "\n".join(sbs) or r"\textit{Sin factores con fuente suficiente para estos criterios.}"

    detalle = []
    for k in DIMENSIONES:
        if k in dims:
            detalle.append(rf"\subsection*{{{NOMBRE_DIM[k]} — {_senal(dims[k].senal)}}}" + "\n"
                           + (rf"\textit{{{esc(dims[k].sintesis)}}}" + "\n\n" if dims[k].sintesis else "")
                           + _items(dims[k].hallazgos, et))

    def lista(xs):
        if not xs:
            return r"\textit{Ninguno.}" + "\n"
        return "\\begin{enumerate}\n" + "\n".join(rf"  \item {esc(x)}" for x in xs) + "\n\\end{enumerate}\n"

    fuentes = "\n".join(
        rf"  \item[\textbf{{[{k}]}}] {esc(d.fuente)}, {esc(d.fecha)}. {esc(d.titulo)}. "
        rf"\href{{{_url(d.url)}}}{{\texttt{{{esc(urlparse(d.url).netloc.removeprefix('www.'))}}}}}"
        for k, d in et.items())

    nota_sin = (r"{\small\textcolor{gris}{Sin fuentes: no encontramos noticias ni registros sobre esa dimensión en la ventana elegida. No significa que no haya riesgo: es un vacío que el auditor debe cubrir.}}"
                if any(d.senal == "sin_evidencia" for d in inf.dimensiones) else "")
    ficha_tex = ""
    if inf.ficha_empresa:
        ficha_tex = ("\\section*{Ficha de la empresa}\n\\begin{itemize}\n"
                     + "\n".join(rf"  \item \textbf{{{esc(NOMBRE_FICHA[d.campo])}:}} {esc(d.valor)} "
                                  rf"{_citas(d.fuentes, et)}" for d in inf.ficha_empresa)
                     + "\n\\end{itemize}\n")

    return rf"""\documentclass[10pt,a4paper]{{article}}
\usepackage[utf8]{{inputenc}}
\usepackage[T1]{{fontenc}}
\usepackage{{lmodern}}
\usepackage[spanish,es-noshorthands,es-nodecimaldot]{{babel}}
\usepackage[margin=2.2cm]{{geometry}}
\usepackage{{amssymb}}
\usepackage[table]{{xcolor}}
\usepackage{{booktabs}}
\usepackage[hidelinks]{{hyperref}}
\definecolor{{verde}}{{HTML}}{{1E8E3E}}
\definecolor{{ambar}}{{HTML}}{{B26A00}}
\definecolor{{rojo}}{{HTML}}{{C5221F}}
\definecolor{{gris}}{{HTML}}{{5F6368}}
\definecolor{{enlace}}{{HTML}}{{1A56DB}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{4pt}}
\hypersetup{{pdftitle={{Contexto crediticio - {esc(datos['empresa'])}}}, pdfauthor={{Auditrail}}}}

\begin{{document}}
{{\small\textcolor{{gris}}{{Auditrail · Papel de trabajo de auditoría interna · Contexto externo del deudor}}}}

{{\LARGE\bfseries {esc(datos['empresa'])}}}\\[2pt]
{{\large Sector {esc(_sector(datos))} \quad·\quad Fecha del análisis: {esc(datos['fecha'])}}}


{ficha_tex}
\section*{{Resumen}}
{esc(inf.resumen_ejecutivo)}

\begin{{center}}
\begin{{tabular}}{{ll}}
\toprule
\textbf{{Dimensión}} & \textbf{{Señal}} \\
\midrule
{tabla_dims} \\
\bottomrule
\end{{tabular}}
\end{{center}}
{nota_sin}

\section*{{Señales externas y alertas}}
\textcolor{{gris}}{{\small {esc(NORMA_ALERTAS)}}}
{_alertas_tex(inf, et)}

\section*{{¿Por qué le estaría yendo bien o mal?}}
{_items(inf.factores_explicativos, et)}

\section*{{Sensibilidad del flujo de caja al entorno (12 meses). Res. SBS N.° 11356-2008, mod. por Res. SBS N.° 2368-2023}}
\textcolor{{gris}}{{\small {esc(NORMA_CPP)} Auditrail no asigna la categoría (Normal, CPP, Deficiente, Dudoso o
Pérdida): la evalúa el auditor frente a la sustentación de la entidad.}}
{sbs_txt}

\section*{{Riesgo único y grupo económico}}
\textcolor{{gris}}{{\small {esc(NORMA_GRUPO)}}}

{_grupo_tex(inf, et)}

\section*{{Puntos de verificación para la auditoría}}
{lista(inf.puntos_de_verificacion)}

\section*{{Vacíos de información}}
{lista(inf.vacios_de_informacion)}

\section*{{Detalle por dimensión}}
{"".join(detalle)}

\section*{{Fuentes}}
{{\small
\begin{{itemize}}
{fuentes}
\end{{itemize}}
}}

\vfill
{{\footnotesize\textcolor{{gris}}{{Generado por Auditrail con {esc(res.get('modelo', ''))} a partir de fuentes públicas
(medios reconocidos, fuentes oficiales y series del BCRP). Toda afirmación cita su fuente; las que no la tenían
se eliminaron ({res.get('descartados', 0)} en este informe). Tokens: entrada {u['input_tokens']:,}, salida
{u['output_tokens']:,}, embeddings {u['embedding_tokens']:,}.}}}}
\end{{document}}
"""


def generar_pdf(datos: dict, res: dict) -> tuple[bytes, str]:
    """PDF listo para descargar: con LaTeX si hay un motor instalado; si no, con reportlab (Python puro)."""
    try:
        pdf, msg = compilar_pdf(informe_latex(datos, res))
    except Exception as e:  # nunca dejar al auditor sin PDF: si LaTeX falla, se usa reportlab
        pdf, msg = None, f"LaTeX falló ({type(e).__name__})."
    if pdf:
        return pdf, msg
    return pdf_reportlab(datos, res), "Generado con reportlab (no hay motor de LaTeX en este equipo)."


# ---------- Respaldo sin LaTeX: el mismo informe, compuesto con reportlab ----------
_HEX = {"verde": "#1E8E3E", "ambar": "#B26A00", "rojo": "#C5221F", "gris": "#5F6368", "enlace": "#1A56DB"}
# Marcas de impacto en Helvetica: + positivo, – negativo, • neutral.
_MARCA = {"positivo": ("+", "verde"), "negativo": ("–", "rojo"), "neutral": ("•", "gris")}


def _x(texto: str) -> str:
    """Escapa para el mini-HTML de reportlab y descarta lo que Helvetica (cp1252) no puede dibujar."""
    from xml.sax.saxutils import escape

    limpio = "".join(c for c in str(texto).replace("≈", "aprox.").replace("→", "->")
                     if c.encode("cp1252", "ignore"))
    return escape(limpio)


def pdf_reportlab(datos: dict, res: dict) -> bytes:
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    inf, et, u = res["informe"], res["etiquetas"], res["uso"]
    base = getSampleStyleSheet()
    st_txt = ParagraphStyle("txt", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13)
    st_item = ParagraphStyle("item", parent=st_txt, leftIndent=14, firstLineIndent=-12, spaceAfter=3)
    st_h1 = ParagraphStyle("h1", parent=base["Title"], fontName="Helvetica-Bold", fontSize=20, alignment=0,
                           spaceAfter=2)
    st_h2 = ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12.5,
                           spaceBefore=10, spaceAfter=4)
    st_h3 = ParagraphStyle("h3", parent=st_txt, fontName="Helvetica-Bold", spaceBefore=4)
    st_gris = ParagraphStyle("gris", parent=st_txt, textColor=colors.HexColor(_HEX["gris"]), fontSize=8.5,
                             leading=11)
    st_impl = ParagraphStyle("impl", parent=st_gris, leftIndent=24, spaceAfter=4)
    st_fuente = ParagraphStyle("fuente", parent=st_gris, leftIndent=14, firstLineIndent=-14, spaceAfter=2)

    def senal(s):
        return f'<font color="{_HEX[COLOR_SENAL[s]]}"><b>{NOMBRE_SENAL[s]}</b></font>'

    def citas(fs):
        return " ".join(f'<a href="{_x(et[f].url)}" color="{_HEX["enlace"]}">[{f}]</a>' for f in fs if f in et)

    def items(hs, prefijo=""):
        if not hs:
            return [Paragraph("<i>Sin factores con fuente suficiente.</i>", st_txt)]
        out = []
        for h in hs:
            letra, color = _MARCA[h.impacto]
            marca = f'<font name="Helvetica-Bold" color="{_HEX[color]}">{letra}</font>&nbsp;&nbsp;'
            out.append(Paragraph(f"{marca}{prefijo}{_x(h.afirmacion)} {citas(h.fuentes)}", st_item))
            if getattr(h, "implicancia", ""):
                out.append(Paragraph(f"<i>Implicancia:</i> {_x(h.implicancia)}", st_impl))
        return out

    def lista(xs):
        if not xs:
            return [Paragraph("<i>Ninguno.</i>", st_txt)]
        return [Paragraph(f"{i}.&nbsp;&nbsp;{_x(x)}", st_item) for i, x in enumerate(xs, 1)]

    dims = {d.nombre: d for d in inf.dimensiones}
    h = [Paragraph("Auditrail · Papel de trabajo de auditoría interna · Contexto externo del deudor", st_gris),
         Paragraph(_x(datos["empresa"]), st_h1),
         Paragraph(f"Sector {_x(_sector(datos))} · Fecha del análisis: {_x(datos['fecha'])}", st_txt),
         ]
    if inf.ficha_empresa:
        h.append(Paragraph("Ficha de la empresa", st_h2))
        h += [Paragraph(f"<b>{_x(NOMBRE_FICHA[d.campo])}:</b> {_x(d.valor)} {citas(d.fuentes)}", st_item)
              for d in inf.ficha_empresa]
    h += [Paragraph("Resumen", st_h2), Paragraph(_x(inf.resumen_ejecutivo), st_txt), Spacer(1, 6)]

    filas = [[Paragraph("<b>Dimensión</b>", st_txt), Paragraph("<b>Señal</b>", st_txt)]]
    filas += [[Paragraph(NOMBRE_DIM[k], st_txt), Paragraph(senal(dims[k].senal if k in dims else "sin_evidencia"),
                                                             st_txt)] for k in DIMENSIONES]
    tabla = Table(filas, colWidths=[5 * cm, 4 * cm])
    tabla.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 1, colors.black),
                               ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                               ("LINEBELOW", (0, -1), (-1, -1), 1, colors.black),
                               ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    h.append(tabla)
    if any(d.senal == "sin_evidencia" for d in inf.dimensiones):
        h.append(Paragraph("Sin fuentes: no encontramos noticias ni registros sobre esa dimensión en la ventana elegida. No significa que no haya riesgo: es un vacío que el auditor debe cubrir.", st_gris))

    h += [Paragraph("Señales externas y alertas", st_h2), Paragraph(_x(NORMA_ALERTAS), st_gris)]
    al = sorted(inf.senales_y_alertas, key=lambda a: RANGO[a.relevancia])
    for c, nombre in CATEGORIAS_ALERTA.items():
        xs = [a for a in al if a.categoria == c]
        if xs:
            h.append(Paragraph(_x(nombre), st_h3))
            for a in xs:
                rel = f'<font name="Helvetica-Bold" size="7.5" color="{_HEX[COLOR_REL[a.relevancia]]}">{a.relevancia.upper()}</font>'
                h.append(Paragraph(f"{rel}&nbsp;&nbsp;<b>{_x(a.fecha_del_hecho)}.</b> {_x(a.afirmacion)} "
                                   f"{citas(a.fuentes)}", st_item))
                if a.implicancia:
                    h.append(Paragraph(f"<i>Implicancia:</i> {_x(a.implicancia)}", st_impl))
    if not al:
        h.append(Paragraph("<i>No se hallaron señales con fuente.</i>", st_txt))
    vacias = [n for c, n in CATEGORIAS_ALERTA.items() if not any(a.categoria == c for a in al)]
    if vacias:
        h.append(Paragraph(f"<b>Sin hallazgos en las fuentes consultadas:</b> {_x('; '.join(vacias))}. "
                           f"{_x(NOTA_VACIAS)}", st_gris))

    h += [Paragraph("¿Por qué le estaría yendo bien o mal?", st_h2), *items(inf.factores_explicativos)]
    h += [Paragraph("Sensibilidad del flujo de caja al entorno (12 meses). Res. SBS N.° 11356-2008, mod. por Res. SBS N.° 2368-2023", st_h2),
          Paragraph(_x(NORMA_CPP) + " Auditrail no asigna la categoría (Normal, CPP, Deficiente, Dudoso o "
                    "Pérdida): la evalúa el auditor frente a la sustentación de la entidad.", st_gris)]
    hay = False
    for crit in CRITERIOS_SBS:
        hs = [x for x in inf.insumos_clasificacion_sbs if x.criterio == crit]
        if hs:
            hay = True
            h += [Paragraph(f"{NOMBRE_CRIT[crit]}. <font color='{_HEX['gris']}' name='Helvetica'>"
                            f"{_x(CRITERIOS_SBS[crit])}</font>", st_h3), *items(hs)]
    if not hay:
        h.append(Paragraph("<i>Sin factores con fuente suficiente para estos criterios.</i>", st_txt))

    g = inf.grupo_economico
    h += [Paragraph("Riesgo único y grupo económico", st_h2), Paragraph(_x(NORMA_GRUPO), st_gris)]
    if g.pertenece != "si":
        h.append(Paragraph(f"<i>{_x(NOTA_SIN_GRUPO)}</i>", st_txt))
    else:
        if g.nombre_del_grupo:
            h.append(Paragraph(f"<b>{_x(g.nombre_del_grupo)}</b>", st_txt))
        if g.sintesis:
            h.append(Paragraph(f"<i>{_x(g.sintesis)}</i>", st_txt))
        for v in [v for v in g.vinculadas if not sin_hechos(v)]:
            letra, color = _MARCA[v.impacto]
            h.append(Paragraph(f'<font name="Helvetica-Bold" color="{_HEX[color]}">{letra}</font>&nbsp;&nbsp;'
                               f"<b>{_x(v.empresa)}</b> ({_x(v.relacion)}): {_x(v.situacion)} {citas(v.fuentes)}",
                               st_item))
        sin = [v for v in g.vinculadas if sin_hechos(v)]
        if sin:
            h.append(Paragraph(f"<b>Otras vinculadas sin hechos relevantes en la evidencia:</b> "
                               f"{_x(', '.join(v.empresa for v in sin)).rstrip('.')}. "
                               f"{citas(sorted({f for v in sin for f in v.fuentes}))}", st_gris))
        h += items(g.hallazgos) if g.hallazgos else []

    h += [Paragraph("Puntos de verificación para la auditoría", st_h2), *lista(inf.puntos_de_verificacion)]
    h += [Paragraph("Vacíos de información", st_h2), *lista(inf.vacios_de_informacion)]
    h.append(Paragraph("Detalle por dimensión", st_h2))
    for k in DIMENSIONES:
        if k in dims:
            h.append(Paragraph(f"{NOMBRE_DIM[k]} — {senal(dims[k].senal)}", st_h3))
            if dims[k].sintesis:
                h.append(Paragraph(f"<i>{_x(dims[k].sintesis)}</i>", st_txt))
            h += items(dims[k].hallazgos)

    h.append(Paragraph("Fuentes", st_h2))
    for k, d in et.items():
        dominio = urlparse(d.url).netloc.removeprefix("www.")
        h.append(Paragraph(f"<b>[{k}]</b>&nbsp;&nbsp;{_x(d.fuente)}, {_x(d.fecha)}. {_x(d.titulo)}. "
                           f'<a href="{_x(d.url)}" color="{_HEX["enlace"]}">{_x(dominio)}</a>', st_fuente))
    h += [Spacer(1, 10), Paragraph(
        f"Generado por Auditrail con {_x(res.get('modelo', ''))} a partir de fuentes públicas (medios reconocidos, "
        f"fuentes oficiales y series del BCRP). Toda afirmación cita su fuente; las que no la tenían se eliminaron "
        f"({res.get('descartados', 0)} en este informe). Tokens: entrada {u['input_tokens']:,}, salida "
        f"{u['output_tokens']:,}, embeddings {u['embedding_tokens']:,}.", st_gris)]

    buf = BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm, topMargin=2 * cm,
                      bottomMargin=2 * cm, title=f"Contexto crediticio - {datos['empresa']}",
                      author="Auditrail").build(h)
    return buf.getvalue()


def motor_disponible() -> str | None:
    for m in ("tectonic", "pdflatex", "xelatex"):
        if shutil.which(m):
            return m
    return None


def compilar_pdf(tex: str, timeout: int = 180) -> tuple[bytes | None, str]:
    """Devuelve (pdf, mensaje). pdf es None si no hay motor de LaTeX o si la compilación falla."""
    motor = motor_disponible()
    if not motor:
        return None, "No hay un motor de LaTeX instalado (tectonic, pdflatex o xelatex)."
    with tempfile.TemporaryDirectory() as d:
        Path(d, "informe.tex").write_text(tex, encoding="utf-8")
        cmd = ([motor, "--keep-logs", "informe.tex"] if motor == "tectonic"
               else [motor, "-interaction=nonstopmode", "-halt-on-error", "informe.tex"])
        try:
            p = subprocess.run(cmd, cwd=d, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout)  # el log de pdflatex puede traer bytes no UTF-8
        except subprocess.TimeoutExpired:
            return None, f"{motor} tardó más de {timeout} s."
        pdf = Path(d, "informe.pdf")
        if p.returncode != 0 or not pdf.exists():
            return None, f"{motor} falló:\n" + (p.stdout + p.stderr)[-1500:]
        return pdf.read_bytes(), f"Compilado con {motor}."
