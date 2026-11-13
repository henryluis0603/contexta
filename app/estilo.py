"""Estilo "liquid glass" ejecutivo para la app: tarjetas translúcidas con desenfoque, azul marino institucional.

Todo el texto que viene del modelo o de las fuentes pasa por html.escape antes de ir al HTML.
"""
from __future__ import annotations

import html

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
  --navy: #1f4e79; --navy-2: #2c6aa0; --ink: #14243a; --muted: #5b6b80;
  --verde: #1e8e3e; --ambar: #b26a00; --rojo: #c5221f; --gris: #7a8699;
  --glass: rgba(255,255,255,0.58); --glass-borde: rgba(255,255,255,0.75);
  --sombra: 0 10px 30px rgba(20,48,82,0.10), 0 1px 0 rgba(255,255,255,0.6) inset;
}
html, body, [class*="css"], .stMarkdown, .stCaption, button, input { font-family: 'Inter', sans-serif !important; }

/* Fondo: degradé frío con dos halos suaves (da profundidad al vidrio) */
.stApp {
  background:
    radial-gradient(900px 500px at 8% -5%, rgba(44,106,160,0.20), transparent 60%),
    radial-gradient(800px 600px at 105% 10%, rgba(31,78,121,0.16), transparent 55%),
    radial-gradient(700px 500px at 50% 110%, rgba(120,170,210,0.18), transparent 60%),
    linear-gradient(160deg, #eef3f9 0%, #e7eef7 45%, #f5f7fb 100%);
  background-attachment: fixed;
}
[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.2rem; max-width: 1180px; }

/* Barra lateral de vidrio */
[data-testid="stSidebar"] > div:first-child {
  background: rgba(255,255,255,0.42);
  backdrop-filter: blur(22px) saturate(170%); -webkit-backdrop-filter: blur(22px) saturate(170%);
  border-right: 1px solid var(--glass-borde);
}

/* Tarjeta de vidrio genérica */
.glass {
  background: var(--glass);
  backdrop-filter: blur(18px) saturate(160%); -webkit-backdrop-filter: blur(18px) saturate(160%);
  border: 1px solid var(--glass-borde); border-radius: 18px; box-shadow: var(--sombra);
  padding: 1.15rem 1.35rem; margin: 0 0 1rem 0; color: var(--ink);
}
.glass h3 { margin: 0 0 .6rem 0; font-size: 1.05rem; font-weight: 650; color: var(--navy); letter-spacing: -.01em; }
.glass .nota { color: var(--muted); font-size: .82rem; margin: -.2rem 0 .7rem 0; }

/* Encabezado */
.hero { padding: 1.4rem 1.6rem; }
.hero .eyebrow { text-transform: uppercase; letter-spacing: .08em; font-size: .72rem; color: var(--muted); font-weight: 600; }
.hero h1 { font-size: 1.9rem; margin: .15rem 0 .2rem 0; color: var(--ink); font-weight: 700; letter-spacing: -.02em; }
.hero .sub { color: var(--muted); font-size: .95rem; }
.ficha { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: .55rem 1.4rem; margin-top: 1rem; }
.ficha div { font-size: .88rem; line-height: 1.35; }
.ficha b { display: block; color: var(--muted); font-weight: 600; font-size: .72rem; text-transform: uppercase; letter-spacing: .05em; }

/* Señales por dimensión */
.dims { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: .8rem; margin-bottom: 1rem; }
.dim { padding: .85rem 1rem; margin: 0; }
.dim .nombre { font-size: .78rem; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: .05em; }
.chip { display: inline-flex; align-items: center; gap: .4rem; margin-top: .35rem; padding: .22rem .65rem;
        border-radius: 999px; font-weight: 600; font-size: .85rem; border: 1px solid transparent; }
.chip::before { content: ""; width: .55rem; height: .55rem; border-radius: 50%; background: currentColor; }
.chip.favorable { color: var(--verde); background: rgba(30,142,62,.10); border-color: rgba(30,142,62,.25); }
.chip.neutral { color: var(--ambar); background: rgba(178,106,0,.10); border-color: rgba(178,106,0,.25); }
.chip.desfavorable { color: var(--rojo); background: rgba(197,34,31,.09); border-color: rgba(197,34,31,.25); }
.chip.sin_evidencia { color: var(--gris); background: rgba(122,134,153,.10); border-color: rgba(122,134,153,.25); }

/* Hallazgos */
.item { display: grid; grid-template-columns: 1.1rem 1fr; gap: .2rem .55rem; padding: .6rem 0;
        border-top: 1px solid rgba(31,78,121,.08); }
.item:first-of-type { border-top: none; }
.marca { font-weight: 700; line-height: 1.45; }
.marca.positivo { color: var(--verde); } .marca.negativo { color: var(--rojo); } .marca.neutral { color: var(--gris); }
.afirm { font-size: .93rem; line-height: 1.5; }
.impl { grid-column: 2; font-size: .85rem; color: var(--muted); line-height: 1.45; padding-left: .6rem;
        border-left: 2px solid rgba(31,78,121,.18); }
.impl b { color: var(--navy); font-weight: 600; }
.cita { display: inline-block; font-size: .72rem; font-weight: 600; color: var(--navy) !important; text-decoration: none !important;
        background: rgba(31,78,121,.08); border: 1px solid rgba(31,78,121,.15); border-radius: 6px; padding: 0 .35rem; margin-left: .15rem; }
.cita:hover { background: rgba(31,78,121,.16); }
.crit { margin-top: .8rem; }
.crit .titulo { font-weight: 650; color: var(--ink); font-size: .92rem; }
.crit .desc { color: var(--muted); font-size: .8rem; }
.sintesis { font-size: .9rem; color: var(--ink); background: rgba(31,78,121,.05); border-radius: 10px; padding: .55rem .75rem; margin-bottom: .3rem; }
ul.lista { margin: 0; padding-left: 1.1rem; } ul.lista li { margin: .3rem 0; font-size: .9rem; line-height: 1.45; }

/* Componentes nativos de Streamlit con el mismo lenguaje */
[data-testid="stExpander"] { background: var(--glass); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--glass-borde) !important; border-radius: 16px !important; box-shadow: var(--sombra); margin-bottom: .6rem; }
[data-testid="stExpander"] details { border: none !important; }
.stButton > button, .stDownloadButton > button {
  border-radius: 12px; font-weight: 600; border: 1px solid rgba(255,255,255,.4);
  box-shadow: 0 6px 18px rgba(31,78,121,.22); }
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
  background: linear-gradient(135deg, var(--navy) 0%, var(--navy-2) 100%); }
.stTabs [data-baseweb="tab-list"] { gap: .4rem; background: rgba(255,255,255,.45); padding: .3rem; border-radius: 14px;
  backdrop-filter: blur(14px); border: 1px solid var(--glass-borde); }
.stTabs [data-baseweb="tab"] { border-radius: 10px; padding: .4rem .9rem; }
.stTabs [aria-selected="true"] { background: rgba(255,255,255,.85); box-shadow: 0 2px 8px rgba(20,48,82,.08); }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display: none; }
[data-testid="stTextInput"] input, [data-baseweb="select"] > div { border-radius: 10px !important; background: rgba(255,255,255,.75) !important; }
[data-testid="stStatusWidget"], [data-testid="stAlert"] { border-radius: 14px; }
</style>
"""

MARCA = {"positivo": "+", "negativo": "–", "neutral": "•"}


def e(x) -> str:
    # Sin saltos de línea: una línea en blanco dentro de un bloque HTML corta el render de st.markdown.
    return html.escape(str(x)).replace("\n", " ")


def citas(fuentes: list[str], etiquetas: dict) -> str:
    return "".join(f'<a class="cita" href="{e(etiquetas[f].url)}" target="_blank" title="{e(etiquetas[f].fuente)}: '
                   f'{e(etiquetas[f].titulo)}">{e(f)}</a>' for f in fuentes if f in etiquetas)


def chip(senal: str, texto: str) -> str:
    return f'<span class="chip {e(senal)}">{e(texto)}</span>'


def item(h, etiquetas: dict) -> str:
    impl = f'<div class="impl"><b>Implicancia:</b> {e(h.implicancia)}</div>' if getattr(h, "implicancia", "") else ""
    return (f'<div class="item"><div class="marca {e(h.impacto)}">{MARCA[h.impacto]}</div>'
            f'<div class="afirm">{e(h.afirmacion)} {citas(h.fuentes, etiquetas)}</div>{impl}</div>')


def tarjeta(titulo: str, cuerpo: str, nota: str = "", clase: str = "") -> str:
    nota_html = f'<div class="nota">{nota}</div>' if nota else ""
    return f'<div class="glass {clase}"><h3>{e(titulo)}</h3>{nota_html}{cuerpo}</div>'
