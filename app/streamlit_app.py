# Contexta — el contexto externo de una empresa, con fuentes, en un minuto.
#     streamlit run app/streamlit_app.py
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(RAIZ / ".env")
# En Streamlit Community Cloud la clave vive en st.secrets, no en .env
try:
    for k in ("OPENAI_API_KEY", "OPENAI_MODEL", "PRICE_INPUT_PER_1M", "PRICE_OUTPUT_PER_1M", "PRICE_EMBED_PER_1M"):
        if k in st.secrets and not os.getenv(k):
            os.environ[k] = str(st.secrets[k])
except Exception:
    pass

from ai.rag import analizar  # noqa: E402
from backend.models import DIMENSIONES  # noqa: E402
from backend.recolector import recolectar  # noqa: E402
from backend.sources.bcrp import SECTORES  # noqa: E402

st.set_page_config(page_title="Contexta · contexto crediticio", page_icon="🔎", layout="wide")

SENAL = {"favorable": ("🟢", "Favorable"), "neutral": ("🟡", "Neutral"),
         "desfavorable": ("🔴", "Desfavorable"), "sin_evidencia": ("⚪", "Sin evidencia")}
IMPACTO = {"positivo": "▲", "negativo": "▼", "neutral": "●"}
NOMBRE_DIM = {"empresa": "Empresa", "sector": "Sector", "macro": "Macroeconomía", "clima": "Clima",
              "regulatorio": "Regulatorio", "social": "Social y político"}

empresas = pd.read_csv(RAIZ / "data" / "empresas_demo.csv")

# ---------------- Barra lateral ----------------
with st.sidebar:
    st.header("🔎 Contexta")
    st.caption("Contexto externo para análisis de crédito empresarial, con cita obligatoria de fuentes.")
    modo = st.radio("Empresa", ["De la lista demo", "Escribir otra"], horizontal=True)
    if modo == "De la lista demo":
        empresa = st.selectbox("Empresa", empresas.empresa)
        sector_def = empresas.set_index("empresa").loc[empresa, "sector"]
    else:
        empresa = st.text_input("Razón social o nombre comercial", "Alicorp")
        sector_def = "Manufactura"
    sectores = list(SECTORES)
    sector = st.selectbox("Sector (clasificación BCRP)", sectores, index=sectores.index(sector_def))
    dias = st.slider("Ventana de noticias (días)", 30, 365, 120, step=30)
    refrescar = st.checkbox("Forzar nueva búsqueda (ignorar caché)", value=False)
    ir = st.button("Analizar contexto", type="primary", width="stretch")

    st.divider()
    key_ok = bool(os.getenv("OPENAI_API_KEY"))
    st.caption(("✅ OpenAI conectado · modelo " + os.getenv("OPENAI_MODEL", "gpt-4.1-mini")) if key_ok
               else "⚠️ Sin OPENAI_API_KEY: se muestra solo la evidencia recuperada (TF-IDF), sin informe.")

st.title("Contexto crediticio de una empresa")
st.caption("Más allá de los estados financieros: macro, sector, clima, regulación, factores sociales y noticias "
           "de la empresa. Cada afirmación lleva su fuente.")

if ir:
    t0 = time.time()
    with st.status("Construyendo el contexto…", expanded=True) as estado:
        st.write("1/3 · Buscando noticias en medios confiables y series oficiales del BCRP…")
        datos = recolectar(empresa, sector, usar_cache=not refrescar, dias=dias)
        docs = datos["documentos"]
        st.write(f"   {len(docs)} documentos ({'caché' if datos.get('desde_cache') else 'en vivo'}).")
        st.write("2/3 · Fragmentando, embebiendo y recuperando evidencia por dimensión…")
        st.write("3/3 · Redactando el informe con citas y validándolas…")
        res = analizar(empresa, sector, docs, datos["fecha"])
        estado.update(label=f"Listo en {time.time() - t0:.0f} s", state="complete", expanded=False)
    st.session_state["res"], st.session_state["datos"] = res, datos

res, datos = st.session_state.get("res"), st.session_state.get("datos")
if not res:
    st.info("Elige una empresa y pulsa **Analizar contexto**.")
    st.stop()

etiquetas = res["etiquetas"]


def citas(fuentes: list[str]) -> str:
    return " ".join(f"[{f}]({etiquetas[f].url})" for f in fuentes if f in etiquetas)


tab_inf, tab_bcrp, tab_ev = st.tabs(["📋 Informe", "📈 Indicadores BCRP", "📚 Evidencia y fuentes"])

# ---------------- Informe ----------------
with tab_inf:
    inf = res["informe"]
    if inf is None:
        st.warning("Sin API key no se genera el informe. Esta es la evidencia más relevante por dimensión:")
        for dim, lista in res["recuperados"].items():
            st.subheader(NOMBRE_DIM[dim])
            vistos = set()
            for frag, s in lista:
                if frag.doc.id in vistos:
                    continue
                vistos.add(frag.doc.id)
                st.markdown(f"- [{frag.doc.titulo}]({frag.doc.url}) · {frag.doc.fuente} · {frag.doc.fecha} "
                            f"· similitud {s:.2f}")
    else:
        ico, txt = SENAL[inf.senal_global]
        c1, c2 = st.columns([3, 1])
        c1.subheader(f"{datos['empresa']} · {datos['sector']}")
        c2.metric("Señal de contexto", f"{ico} {txt}")
        st.markdown(f"**Resumen para el comité.** {inf.resumen_ejecutivo}")

        cols = st.columns(6)
        orden = {d.nombre: d for d in inf.dimensiones}
        for col, dim in zip(cols, DIMENSIONES):
            d = orden.get(dim)
            i, t = SENAL[d.senal if d else "sin_evidencia"]
            col.metric(NOMBRE_DIM[dim], f"{i} {t}")

        st.markdown("### ¿Por qué le estaría yendo bien o mal?")
        for h in inf.factores_explicativos:
            st.markdown(f"{IMPACTO[h.impacto]} {h.afirmacion} {citas(h.fuentes)}")

        st.markdown("### Detalle por dimensión")
        for dim in DIMENSIONES:
            d = orden.get(dim)
            if not d:
                continue
            i, t = SENAL[d.senal]
            with st.expander(f"{i} {NOMBRE_DIM[dim]} — {t}", expanded=d.senal == "desfavorable"):
                if not d.hallazgos:
                    st.caption("Sin evidencia suficiente en las fuentes recuperadas.")
                for h in d.hallazgos:
                    st.markdown(f"{IMPACTO[h.impacto]} {h.afirmacion} {citas(h.fuentes)}")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("### Preguntas para el cliente")
            for p in inf.preguntas_para_el_cliente:
                st.markdown(f"- {p}")
        with c2:
            st.markdown("### Vacíos de información")
            for v in inf.vacios_de_informacion:
                st.markdown(f"- {v}")

        u = res["uso"]
        costo = f" · costo ≈ US$ {u['costo_usd']}" if u.get("costo_usd") is not None else ""
        st.caption(f"Modelo {res['modelo']} · {res['embedder']} · tokens: entrada {u['input_tokens']:,}, "
                   f"salida {u['output_tokens']:,}, embeddings {u['embedding_tokens']:,}{costo} · "
                   f"{res['descartados']} afirmaciones descartadas por no tener fuente válida.")

        md = [f"# Contexto crediticio · {datos['empresa']} ({datos['sector']})", f"Fecha: {datos['fecha']}",
              f"\n**Señal global:** {txt}\n", inf.resumen_ejecutivo, "\n## Factores explicativos"]
        md += [f"- {h.afirmacion} ({', '.join(h.fuentes)})" for h in inf.factores_explicativos]
        for d in inf.dimensiones:
            md.append(f"\n## {NOMBRE_DIM[d.nombre]} — {SENAL[d.senal][1]}")
            md += [f"- {h.afirmacion} ({', '.join(h.fuentes)})" for h in d.hallazgos]
        md.append("\n## Preguntas para el cliente")
        md += [f"- {p}" for p in inf.preguntas_para_el_cliente]
        md.append("\n## Fuentes")
        md += [f"- [{k}] {v.fuente}, {v.fecha}: {v.titulo} — {v.url}" for k, v in etiquetas.items()]
        st.download_button("Descargar informe (.md)", "\n".join(md),
                           file_name=f"contexto_{datos['empresa'].replace(' ', '_')}.md")

# ---------------- Indicadores ----------------
with tab_bcrp:
    st.caption("Series oficiales descargadas de la API del BCRP. Las cifras las calcula Python, no el modelo.")
    series = datos["series"]
    for a, b in zip(series[0::2], series[1::2] + [None]):
        cols = st.columns(2)
        for col, s in zip(cols, (a, b)):
            if not s:
                continue
            df = pd.DataFrame(s["datos"])
            fig = go.Figure(go.Scatter(x=df.periodo, y=df.valor, mode="lines+markers", line=dict(width=2)))
            fig.update_layout(title=f"{s['etiqueta']} · {s['codigo']}",
                              height=280, margin=dict(l=10, r=10, t=40, b=10), yaxis_title=s["unidad"])
            col.plotly_chart(fig, width="stretch")

# ---------------- Evidencia ----------------
with tab_ev:
    st.caption("Solo se usan fuentes oficiales y medios reconocidos; redes sociales y blogs se descartan.")
    filas = [{"Etiqueta": k, "Fuente": v.fuente, "Fecha": v.fecha, "Dimensión": NOMBRE_DIM.get(v.dimension),
              "Tipo": v.tipo, "Título": v.titulo, "URL": v.url} for k, v in etiquetas.items()]
    st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch",
                 column_config={"URL": st.column_config.LinkColumn("URL")})
    with st.expander("Ver el texto exacto que recibió el modelo"):
        st.text(res["evidencia"])
