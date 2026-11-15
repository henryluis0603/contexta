# Auditrail — el entorno del deudor, con evidencia auditable: cada afirmación deja su rastro hasta la fuente.
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

load_dotenv(RAIZ / ".env", override=True)  # override: si cambias la clave en .env, basta recargar
# En Streamlit Community Cloud la clave vive en st.secrets, no en .env
try:
    for k in ("OPENAI_API_KEY", "TAVILY_API_KEY", "OPENAI_MODEL", "PRICE_INPUT_PER_1M", "PRICE_OUTPUT_PER_1M", "PRICE_EMBED_PER_1M"):
        if k in st.secrets and not os.getenv(k):
            os.environ[k] = str(st.secrets[k])
except Exception:
    pass

from ai.rag import analizar, sin_hechos  # noqa: E402
from backend.models import (CATEGORIAS_ALERTA, CRITERIOS_SBS, DIMENSIONES, NOMBRE_CRIT,  # noqa: E402
                            NOMBRE_DIM, NOMBRE_FICHA, NORMA_ALERTAS, NORMA_CPP, NORMA_GRUPO, NORMA_MYPE)
from app.estilo import CSS, alerta, chip, e, item, tarjeta, vinculada  # noqa: E402
from app.estilo import citas as citas_h  # noqa: E402
from backend.reporte_pdf import generar_pdf  # noqa: E402
from backend.recolector import recolectar  # noqa: E402
from ai.detectar_sector import detectar_sector  # noqa: E402
from backend.sources.bcrp import SECTORES, SUBSECTORES  # noqa: E402
from backend.sources.web import proveedor as proveedor_web  # noqa: E402

st.set_page_config(page_title="Auditrail · el entorno del deudor, con evidencia auditable", page_icon="🔎", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

SENAL = {"favorable": ("🟢", "Favorable"), "neutral": ("🟡", "Neutral"),
         "desfavorable": ("🔴", "Desfavorable"), "sin_evidencia": ("⚪", "Sin fuentes")}

empresas = pd.read_csv(RAIZ / "data" / "empresas_demo.csv")
detectar_cacheado = st.cache_data(ttl=24 * 3600, show_spinner=False)(detectar_sector)

# ---------------- Barra lateral ----------------
with st.sidebar:
    st.header("🔎 Auditrail")
    st.caption("El entorno del deudor, con evidencia auditable. Para auditoría interna de la clasificación crediticia.")
    modo = st.radio("Empresa", ["Escribir empresa", "De la lista demo"], horizontal=True)
    if modo == "De la lista demo":
        empresa = st.selectbox("Empresa", empresas.empresa)
        fila = empresas.set_index("empresa").loc[empresa]
        if st.session_state.get("clasif_de") != ("demo", empresa):
            st.session_state.update(clasif_de=("demo", empresa), sector_sel=fila.sector,
                                    subsector_sel=fila.subsector, deteccion=None)
    else:
        empresa = st.text_input("Razón social o nombre comercial", placeholder="p. ej. María Almenara",
                                help="Pulsa Enter: Auditrail detecta el sector y subsector con noticias recientes.")
        empresa = empresa.strip()
        if empresa and st.session_state.get("clasif_de") != ("texto", empresa):
            with st.spinner("Detectando el sector con noticias recientes…"):
                det = detectar_cacheado(empresa)
            st.session_state.update(clasif_de=("texto", empresa), deteccion=det)
            if det:
                st.session_state.update(sector_sel=det["sector"], subsector_sel=det["subsector"])
        det = st.session_state.get("deteccion")
        if det and det["confianza"] != "baja":
            st.caption(f"🔎 **Detectado** (confianza {det['confianza']}): {det['actividad']} "
                       f"Según «{det['titular']}» ({det['medio']}). Puedes cambiarlo abajo.")
        elif det:
            st.warning("No encontré noticias suficientes para saber a qué se dedica. Revisa el sector.")
        elif empresa and not os.getenv("OPENAI_API_KEY"):
            st.caption("Elige el sector a mano: la detección automática necesita OPENAI_API_KEY.")

    sectores = list(SECTORES)
    if st.session_state.get("sector_sel") not in sectores:
        st.session_state["sector_sel"] = sectores[0]
    sector = st.selectbox("Sector (clasificación BCRP)", sectores, key="sector_sel")
    subsectores = list(SUBSECTORES[sector])
    if st.session_state.get("subsector_sel") not in subsectores:
        st.session_state["subsector_sel"] = subsectores[0]
    subsector = st.selectbox("Subsector", subsectores, key="subsector_sel",
                             help="Afina la búsqueda de noticias y, cuando el BCRP la publica, suma la serie del subsector.")
    dias = st.slider("Ventana de noticias (días)", 30, 365, 120, step=30)
    refrescar = st.checkbox("Forzar nueva búsqueda (ignorar caché)", value=False)
    ir = st.button("Analizar contexto", type="primary", width="stretch", disabled=not empresa)

    st.divider()
    key_ok = bool(os.getenv("OPENAI_API_KEY"))
    st.caption(("✅ OpenAI conectado · modelo " + os.getenv("OPENAI_MODEL", "gpt-4.1-mini")) if key_ok
               else "⚠️ Sin OPENAI_API_KEY: se muestra solo la evidencia recuperada (TF-IDF), sin informe.")
    prov_web = proveedor_web()
    st.caption(f"✅ Búsqueda web conectada ({'Tavily' if prov_web == 'tavily' else 'OpenAI web search'})"
               if prov_web else "⚠️ Sin búsqueda web: solo noticias; las empresas que no salen en medios quedan sin ficha.")

st.markdown('<div style="margin:-.4rem 0 1rem 0"><span style="font-size:1.55rem;font-weight:700;color:#14243a;'
            'letter-spacing:-.02em">Contexto crediticio</span><span style="color:#5b6b80;font-size:.92rem;'
            'margin-left:.7rem">Macro, sector, clima, regulación, factores sociales y la propia empresa · '
            'cada afirmación con su fuente</span></div>', unsafe_allow_html=True)

if ir:
    t0 = time.time()
    with st.status("Construyendo el contexto…", expanded=True) as estado:
        st.write("1/3 · Buscando noticias, series del BCRP, ficha, grupo económico y alertas…")
        datos = recolectar(empresa, sector, usar_cache=not refrescar, dias=dias, subsector=subsector)
        docs = datos["documentos"]
        st.write(f"   {len(docs)} documentos ({'caché' if datos.get('desde_cache') else 'en vivo'}).")
        st.write("2/3 · Fragmentando, embebiendo y recuperando evidencia por dimensión…")
        st.write("3/3 · Redactando el informe con citas y validándolas…")
        res = analizar(empresa, f"{sector} › {subsector}", docs, datos["fecha"])
        estado.update(label=f"Listo en {time.time() - t0:.0f} s", state="complete", expanded=False)
    st.session_state["res"], st.session_state["datos"] = res, datos

res, datos = st.session_state.get("res"), st.session_state.get("datos")
if not res:
    st.info("Elige una empresa y pulsa **Analizar contexto**.")
    st.stop()

etiquetas = res["etiquetas"]



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
        orden = {d.nombre: d for d in inf.dimensiones}
        html_ = st.markdown  # alias corto

        # Encabezado + ficha
        sector_txt = " › ".join(x for x in (datos["sector"], datos.get("subsector")) if x)
        ficha = "".join(f"<div><b>{e(NOMBRE_FICHA[d.campo])}</b>{e(d.valor)} {citas_h(d.fuentes, etiquetas)}</div>"
                        for d in inf.ficha_empresa)
        html_(f'<div class="glass hero"><div class="eyebrow">Papel de trabajo · Contexto externo del deudor</div>'
              f'<h1>{e(datos["empresa"])}</h1><div class="sub">{e(sector_txt)} · Análisis del {e(datos["fecha"])}</div>'
              + (f'<div class="ficha">{ficha}</div>' if ficha else "") + "</div>", unsafe_allow_html=True)

        html_(tarjeta("Resumen", f'<div class="afirm">{e(inf.resumen_ejecutivo)}</div>'), unsafe_allow_html=True)

        # Señales externas y alertas, por categoría y ordenadas por relevancia
        rango = {"alta": 0, "media": 1, "baja": 2}
        al = sorted(inf.senales_y_alertas, key=lambda a: rango[a.relevancia])
        conteo = "".join(chip({"alta": "desfavorable", "media": "neutral", "baja": "sin_evidencia"}[r],
                              f"{n} de relevancia {r}") for r in rango
                         if (n := sum(a.relevancia == r for a in al)))
        cats = [f'<div class="cat"><div class="titulo">{e(nombre)}</div>'
                + "".join(alerta(a, etiquetas) for a in al if a.categoria == c) + "</div>"
                for c, nombre in CATEGORIAS_ALERTA.items() if any(a.categoria == c for a in al)]
        vacias = [n for c, n in CATEGORIAS_ALERTA.items() if not any(a.categoria == c for a in al)]
        html_(tarjeta("Señales externas y alertas",
                      (f'<div class="resumen-alertas">{conteo}</div>' if conteo else "")
                      + ("".join(cats) or '<div class="nota">No se hallaron señales con fuente.</div>')
                      + (f'<div class="vacias"><b>Sin hallazgos en las fuentes consultadas:</b> '
                         f'{e("; ".join(vacias))}. No equivale a una constancia negativa: confírmalo en las '
                         f'fuentes oficiales y en las listas internas del banco.</div>' if vacias else ""),
                      nota=e(NORMA_ALERTAS)), unsafe_allow_html=True)

        # Señal por dimensión
        celdas = "".join(
            f'<div class="glass dim"><div class="nombre">{e(NOMBRE_DIM[k])}</div>'
            f'{chip(orden[k].senal if k in orden else "sin_evidencia", SENAL[orden[k].senal if k in orden else "sin_evidencia"][1])}</div>'
            for k in DIMENSIONES)
        html_(f'<div class="dims">{celdas}</div>', unsafe_allow_html=True)
        if any(d.senal == "sin_evidencia" for d in inf.dimensiones):
            st.caption("*Sin fuentes* significa que no encontramos noticias ni registros sobre esa dimensión en la "
                       "ventana elegida. **No significa que no haya riesgo**: es un vacío que el auditor debe cubrir.")

        html_(tarjeta("¿Por qué le estaría yendo bien o mal?",
                      "".join(item(h, etiquetas) for h in inf.factores_explicativos)
                      or '<div class="nota">Sin factores con fuente suficiente.</div>'), unsafe_allow_html=True)

        bloques = []
        for crit, desc in CRITERIOS_SBS.items():
            hs = [h for h in inf.insumos_clasificacion_sbs if h.criterio == crit]
            if hs:
                bloques.append(f'<div class="crit"><div class="titulo">{e(NOMBRE_CRIT[crit])}</div>'
                               f'<div class="desc">{e(desc)}</div>' + "".join(item(h, etiquetas) for h in hs) + "</div>")
        es_mype = any(d.campo == "tipo_de_credito_referencial" and ("pequeña" in d.valor.lower()
                      or "micro" in d.valor.lower()) for d in inf.ficha_empresa)
        html_(tarjeta("Sensibilidad del flujo de caja al entorno (12 meses) · Res. SBS N.° 11356-2008, mod. por Res. SBS N.° 2368-2023",
                      "".join(bloques) or '<div class="nota">Sin factores con fuente suficiente para estos criterios.</div>',
                      nota=e(NORMA_CPP) + " Auditrail no asigna la categoría: la evalúa el auditor frente a la "
                           "sustentación de la entidad." + (" " + e(NORMA_MYPE) if es_mype else "")),
              unsafe_allow_html=True)

        # Riesgo único y grupo económico
        g = inf.grupo_economico
        if g.pertenece == "si":
            cuerpo_g = ((f'<div class="grupo-nombre">{e(g.nombre_del_grupo)}</div>' if g.nombre_del_grupo else "")
                        + (f'<div class="sintesis">{e(g.sintesis)}</div>' if g.sintesis else "")
                        + "".join(vinculada(v, etiquetas) for v in g.vinculadas if not sin_hechos(v))
                        + (f'<div class="vacias"><b>Otras vinculadas sin hechos relevantes en la evidencia:</b> '
                           f'{e(", ".join(v.empresa for v in g.vinculadas if sin_hechos(v)))} '
                           f'{citas_h(sorted({f for v in g.vinculadas if sin_hechos(v) for f in v.fuentes}), etiquetas)}</div>'
                           if any(sin_hechos(v) for v in g.vinculadas) else "")
                        + "".join(item(h, etiquetas) for h in g.hallazgos))
        else:
            cuerpo_g = ('<div class="nota">No se halló evidencia pública de que la empresa pertenezca a un grupo '
                        'económico. Verifícalo con la información de vinculación del expediente y del RCC.</div>')
        html_(tarjeta("Riesgo único y grupo económico", cuerpo_g, nota=e(NORMA_GRUPO)), unsafe_allow_html=True)

        st.markdown("#### Detalle por dimensión")
        for dim in DIMENSIONES:
            d = orden.get(dim)
            if not d:
                continue
            with st.expander(f"{SENAL[d.senal][0]}  {NOMBRE_DIM[dim]} — {SENAL[d.senal][1]}",
                             expanded=d.senal == "desfavorable"):
                cuerpo = (f'<div class="sintesis">{e(d.sintesis)}</div>' if d.sintesis else "")
                cuerpo += "".join(item(h, etiquetas) for h in d.hallazgos) or \
                    '<div class="nota">Sin fuentes en la ventana elegida.</div>'
                html_(cuerpo, unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        lista = lambda xs: '<ul class="lista">' + "".join(f"<li>{e(x)}</li>" for x in xs) + "</ul>"  # noqa: E731
        c1.markdown(tarjeta("Puntos de verificación para la auditoría", lista(inf.puntos_de_verificacion)),
                    unsafe_allow_html=True)
        c2.markdown(tarjeta("Vacíos de información", lista(inf.vacios_de_informacion)), unsafe_allow_html=True)

        u = res["uso"]
        costo = f" · costo ≈ US$ {u['costo_usd']}" if u.get("costo_usd") is not None else ""
        st.caption(f"Modelo {res['modelo']} · {res['embedder']} · tokens: entrada {u['input_tokens']:,}, "
                   f"salida {u['output_tokens']:,}, embeddings {u['embedding_tokens']:,}{costo} · "
                   f"{res['descartados']} afirmaciones descartadas por no tener fuente válida.")

        # Informe en PDF (LaTeX si hay motor; si no, reportlab). Se genera una sola vez por informe.
        if st.session_state.get("pdf_de") is not inf:
            with st.spinner("Preparando el PDF…"):
                st.session_state["pdf"], _ = generar_pdf(datos, res)
            st.session_state["pdf_de"] = inf
        st.download_button("📄 Descargar informe (PDF)", st.session_state["pdf"],
                           file_name=f"contexto_{datos['empresa'].replace(' ', '_')}.pdf",
                           mime="application/pdf", type="primary")

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
