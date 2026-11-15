"""RAG con citas obligatorias (sesión 08): fragmentar -> embeber -> recuperar por dimensión -> generar con
salida estructurada -> validar que cada afirmación cite una fuente que de verdad se recuperó.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from ai.prompts import SISTEMA, USUARIO
from backend.models import DIMENSIONES, MODULOS, Documento

EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
CHAT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

Senal = Literal["favorable", "neutral", "desfavorable", "sin_evidencia"]


# ---------- Salida estructurada ----------
class Hallazgo(BaseModel):
    afirmacion: str = Field(description="Hecho concreto, con cifra, periodo y contexto si la evidencia los tiene "
                                        "(1 a 2 oraciones)")
    implicancia: str = Field(description="Cómo ese hecho puede afectar la capacidad de pago del deudor: canal "
                                         "(ventas, costos, márgenes, liquidez, operación) y horizonte. Es análisis, "
                                         "no un hecho nuevo: no agregues cifras que no estén en la evidencia")
    impacto: Literal["positivo", "negativo", "neutral"]
    fuentes: list[str] = Field(description='Etiquetas de la evidencia que lo respaldan, p. ej. ["S2", "S7"]')


class Dimension(BaseModel):
    nombre: Literal["empresa", "sector", "macro", "clima", "regulatorio", "social"]
    senal: Senal
    sintesis: str = Field(description="2 a 3 oraciones que integran los hallazgos y justifican la señal")
    hallazgos: list[Hallazgo] = Field(description="2 a 4 hallazgos si hay evidencia suficiente")


class AlertaSBS(Hallazgo):
    """Factor externo agrupado por el criterio de entorno de la Res. SBS N.° 11356-2008 al que sirve de insumo."""

    criterio: Literal["entorno_economico", "riesgo_cambiario", "entorno_comercial", "entorno_politico_regulatorio"]


class DatoFicha(BaseModel):
    campo: Literal["razon_social", "nombre_comercial", "ruc", "actividad_principal", "estado_y_condicion",
                   "inicio_de_actividades", "ubicacion", "escala_u_operaciones", "habilitaciones_y_permisos",
                   "ventas_o_ingresos_anuales", "grupo_economico", "tipo_de_credito_referencial"]
    valor: str = Field(description="Tal como aparece en la fuente. Nunca nombres de personas naturales")
    fuentes: list[str]


class Vinculada(BaseModel):
    empresa: str = Field(description="Razón social de la empresa vinculada (nunca una persona natural)")
    relacion: str = Field(description="Matriz, subsidiaria, misma matriz, participación de X %, etc., según la fuente")
    situacion: str = Field(description="Hechos recientes relevantes para su riesgo de crédito, con cifra y fecha si "
                                       "la evidencia los tiene; o 'Sin hechos relevantes en la evidencia'")
    impacto: Literal["positivo", "negativo", "neutral"]
    fuentes: list[str]


def sin_hechos(v: "Vinculada") -> bool:
    """Vinculada listada solo por la estructura del grupo, sin hechos recientes."""
    return v.situacion.strip().lower().startswith(("sin hechos", "no se", "sin información"))


class GrupoEconomico(BaseModel):
    pertenece: Literal["si", "no_hallado"] = Field(description='"si" solo si una fuente lo dice')
    nombre_del_grupo: str = Field(description='Nombre del grupo o holding; "" si no se halló')
    sintesis: str = Field(description="2 a 4 oraciones: estructura del grupo, situación del grupo y cómo puede "
                                      "afectar al deudor (soporte o contagio). Vacío si no se halló")
    vinculadas: list[Vinculada]
    hallazgos: list[Hallazgo] = Field(description="Hechos del grupo que afectan el riesgo único del deudor")


class AlertaExterna(Hallazgo):
    """Señal externa con fecha, agrupada por categoría (rating, sanción, proceso, conflicto, reputación, proyecto)."""

    categoria: Literal["clasificacion_de_riesgo", "hecho_de_importancia", "sancion_administrativa",
                       "proceso_concursal_o_judicial", "conflicto_social_o_ambiental", "reputacional_o_laft",
                       "proyecto_futuro"]
    fecha_del_hecho: str = Field(description="Fecha o periodo del hecho según la fuente; 's/f' si no la tiene")
    relevancia: Literal["alta", "media", "baja"] = Field(
        description="alta: puede afectar la capacidad de pago o exige sustentación en el expediente; media: debe "
                    "conocerse; baja: informativa")


class Informe(BaseModel):
    ficha_empresa: list[DatoFicha] = Field(
        description="Datos de identificación de la empresa que aparezcan en la evidencia (registros, gob.pe, "
                    "directorios RUC, medios). Omite los campos sin evidencia.")
    resumen_ejecutivo: str = Field(
        description="6 a 8 oraciones en un párrafo: (1) qué hace la empresa y su escala; (2) principales factores "
                    "externos a favor; (3) principales factores en contra; (4) qué criterios de entorno SBS concentran "
                    "el riesgo; (5) alertas de relevancia alta y situación del grupo económico, si las hay; (6) qué dimensiones \
no tienen fuentes. Con cifras y periodos de la evidencia")
    factores_explicativos: list[Hallazgo] = Field(description="Por qué le va bien o mal, más allá de los EEFF")
    senales_y_alertas: list[AlertaExterna] = Field(
        description="Señales externas sobre la propia empresa: rating, hechos de importancia, sanciones, procesos, "
                    "conflictos, reputación y LA/FT, proyectos. Solo hechos con fuente; nada si no hay")
    grupo_economico: GrupoEconomico
    dimensiones: list[Dimension]
    insumos_clasificacion_sbs: list[AlertaSBS] = Field(
        description="Variables del entorno a las que el flujo de caja del deudor podría ser sensible en los "
                    "próximos 12 meses (numeral 2.2 a) del Reglamento, modificado por la Res. SBS 2368-2023), "
                    "agrupadas por criterio. Nunca propone una categoría.")
    puntos_de_verificacion: list[str] = Field(
        description="Qué debe revisar el auditor en el expediente y en la sustentación de la clasificación, "
                    "con la etiqueta de la fuente que lo motiva, p. ej. [S8]")
    vacios_de_informacion: list[str]


# ---------- Fragmentación ----------
@dataclass
class Fragmento:
    id: str
    doc: Documento
    texto: str


def fragmentar(docs: list[Documento], tam: int = 900, solape: int = 150) -> list[Fragmento]:
    """Corta por párrafos hasta ~tam caracteres, con solape para no partir ideas."""
    out = []
    for d in docs:
        if len(d.texto) <= tam:
            out.append(Fragmento(f"{d.id}#0", d, d.texto))
            continue
        parrafos = [p.strip() for p in re.split(r"\n+", d.texto) if p.strip()]
        actual, i = "", 0
        for p in parrafos:
            if actual and len(actual) + len(p) > tam:
                out.append(Fragmento(f"{d.id}#{i}", d, actual))
                i += 1
                actual = actual[-solape:] + " " + p
            else:
                actual = (actual + "\n" + p).strip()
        if actual:
            out.append(Fragmento(f"{d.id}#{i}", d, actual))
    return out


# ---------- Embeddings ----------
class EmbedderOpenAI:
    nombre = f"OpenAI {EMBED_MODEL}"

    def __init__(self, client):
        self.client = client
        self.tokens = 0

    def fit(self, textos):  # no necesita ajuste
        return self

    def __call__(self, textos: list[str]) -> np.ndarray:
        vecs = []
        for i in range(0, len(textos), 96):
            r = self.client.embeddings.create(model=EMBED_MODEL, input=textos[i:i + 96])
            self.tokens += r.usage.total_tokens
            vecs += [e.embedding for e in r.data]
        return np.array(vecs, dtype=np.float32)


class EmbedderTFIDF:
    """Respaldo sin API key: TF-IDF. Peor que embeddings densos, pero permite la demo offline."""

    nombre = "TF-IDF (sin API key)"
    tokens = 0

    def fit(self, textos):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.vec = TfidfVectorizer(strip_accents="unicode", lowercase=True, ngram_range=(1, 2), min_df=1,
                                   sublinear_tf=True)
        self.vec.fit(textos)
        return self

    def __call__(self, textos):
        return self.vec.transform(textos).toarray().astype(np.float32)


class Indice:
    def __init__(self, fragmentos: list[Fragmento], embedder):
        self.frags = fragmentos
        self.emb = embedder.fit([f.texto for f in fragmentos])
        m = self.emb([f"{f.doc.titulo}. {f.texto}" for f in fragmentos])
        self.m = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)

    def buscar(self, consulta: str, k: int = 6, preferir: str | None = None, bonus: float = 0.05,
               filtro=None) -> list[tuple[Fragmento, float]]:
        """Similitud coseno; `preferir` suma un bonus a los fragmentos cuya búsqueda de origen fue esa dimensión;
        `filtro(fragmento) -> bool` restringe a qué fragmentos se puede devolver."""
        q = self.emb([consulta])[0]
        q = q / (np.linalg.norm(q) + 1e-9)
        s = self.m @ q
        if preferir:
            s = s + bonus * np.array([f.doc.dimension == preferir for f in self.frags])
        orden = [i for i in np.argsort(-s) if filtro is None or filtro(self.frags[i])]
        return [(self.frags[i], float(s[i])) for i in orden[:k]]


# ---------- Recuperación por dimensión ----------
def recuperar(indice: Indice, empresa: str, sector: str, k: int = 6) -> dict[str, list[tuple[Fragmento, float]]]:
    """Una consulta por dimensión, con cupo propio: primero los fragmentos de las noticias que se buscaron para esa
    dimensión y, si faltan, el resto. Sin el cupo, las páginas que repiten el nombre de la empresa acaparaban
    todas las dimensiones y las noticias de paros o normas nunca llegaban al modelo. Las páginas web de la
    empresa no compiten aquí: entran siempre en armar_evidencia."""
    out = {}
    for dim, desc in DIMENSIONES.items():
        consulta = f"{empresa} (sector {sector}). {desc}"
        propios = indice.buscar(consulta, k=k, filtro=lambda f, d=dim: f.doc.dimension == d
                                and not f.doc.tipo.startswith("web_"))
        if len(propios) < k:
            ya = {id(f) for f, _ in propios}
            propios += indice.buscar(consulta, k=k - len(propios), preferir=dim,
                                     filtro=lambda f: id(f) not in ya and not f.doc.tipo.startswith("web_"))
        out[dim] = propios
    # Grupo económico y alertas: solo con sus propias noticias (sin relleno, para no forzar evidencia ajena).
    for mod, desc in MODULOS.items():
        out[mod] = indice.buscar(f"{empresa}. {desc}", k=4, filtro=lambda f, m=mod: f.doc.dimension == m
                                 and not f.doc.tipo.startswith("web_"))
    return out


def armar_evidencia(recuperados: dict, docs: list[Documento]) -> tuple[str, dict[str, Documento]]:
    """Etiqueta cada documento como S1..Sn y arma el bloque de evidencia que verá el modelo.

    Las series del BCRP entran siempre: son cortas y son la base cuantitativa del informe.
    """
    por_doc: dict[str, list[str]] = {}
    for d in docs:
        if d.tipo == "serie_bcrp":
            por_doc.setdefault(d.id, []).append(d.texto)
    # Los resultados web de la empresa (registros, gob.pe) también entran siempre: son la base de la ficha.
    # Con OpenAI web search varias páginas comparten la misma síntesis: se incluye completa una sola vez.
    vistos_web: dict[str, str] = {}
    web = [d for d in docs if d.tipo.startswith("web_")]
    for d in [x for dim in ("empresa", *MODULOS) for x in web if x.dimension == dim][:20]:
        texto = d.texto[:3500]
        if texto in vistos_web:
            texto = f"(Página citada por la misma síntesis de búsqueda web que el documento {vistos_web[texto]}.)"
        else:
            vistos_web[texto] = d.titulo[:80]
        por_doc.setdefault(d.id, []).append(texto)
    for lista in recuperados.values():
        for frag, _ in lista:
            textos = por_doc.setdefault(frag.doc.id, [])
            if frag.texto not in textos:
                textos.append(frag.texto)

    mapa_docs = {d.id: d for d in docs}
    etiquetas: dict[str, Documento] = {}
    bloques = []
    for i, (doc_id, textos) in enumerate(por_doc.items(), start=1):
        d = mapa_docs[doc_id]
        et = f"S{i}"
        etiquetas[et] = d
        rotulo = {"web_oficial": " (fuente oficial)", "web_directorio": " (directorio web; replica registros)",
                  "noticia_oficial": " (fuente oficial)"}.get(d.tipo, "")
        bloques.append(f"[{et}]{rotulo} {d.fuente} · {d.fecha} · {d.titulo}\n" + "\n…\n".join(textos))
    return "\n\n".join(bloques), etiquetas


def validar(informe: Informe, etiquetas: dict) -> tuple[Informe, int]:
    """Elimina citas inventadas y los hallazgos que se quedan sin ninguna fuente válida."""
    descartados = 0

    def limpiar(hs: list[Hallazgo]) -> list[Hallazgo]:
        nonlocal descartados
        out = []
        for h in hs:
            h.fuentes = [f.strip("[] ") for f in h.fuentes if f.strip("[] ") in etiquetas]
            if h.fuentes:
                out.append(h)
            else:
                descartados += 1
        return out

    informe.ficha_empresa = limpiar(informe.ficha_empresa)
    informe.factores_explicativos = limpiar(informe.factores_explicativos)
    informe.insumos_clasificacion_sbs = limpiar(informe.insumos_clasificacion_sbs)
    # Una "alerta" que solo dice que no se encontró nada no es un hecho: se descarta.
    negativas = re.compile(r"^\s*(no se (encontr|hall|report|registr|identific)|sin (registros|hallazgos|reportar)|"
                           r"no (hay|existen|presenta))", re.I)
    informe.senales_y_alertas = [a for a in limpiar(informe.senales_y_alertas)
                                 if not negativas.search(a.afirmacion) and "sin reportar" not in a.afirmacion.lower()]
    g = informe.grupo_economico
    g.vinculadas, g.hallazgos = limpiar(g.vinculadas), limpiar(g.hallazgos)
    if g.pertenece == "si" and not (g.vinculadas or g.hallazgos):
        g.pertenece, g.nombre_del_grupo, g.sintesis = "no_hallado", "", ""
    for d in informe.dimensiones:
        d.hallazgos = limpiar(d.hallazgos)
        if not d.hallazgos:
            d.senal = "sin_evidencia"
    return informe, descartados


# ---------- Orquestación ----------
def analizar(empresa: str, sector: str, docs: list[Documento], fecha: str, api_key: str | None = None) -> dict:
    """Pipeline completo. Sin API key devuelve solo la evidencia recuperada (modo offline)."""
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    client = None
    if api_key:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)

    frags = fragmentar(docs)
    embedder = EmbedderOpenAI(client) if client else EmbedderTFIDF()
    indice = Indice(frags, embedder)
    recuperados = recuperar(indice, empresa, sector)
    evidencia, etiquetas = armar_evidencia(recuperados, docs)

    out = {"etiquetas": etiquetas, "recuperados": recuperados, "evidencia": evidencia,
           "embedder": embedder.nombre, "n_fragmentos": len(frags), "informe": None,
           "uso": {"embedding_tokens": embedder.tokens, "input_tokens": 0, "output_tokens": 0}}
    if not client:
        return out

    # Los modelos de razonamiento (o*, gpt-5*) no aceptan temperature.
    extra = {} if CHAT_MODEL.startswith(("o", "gpt-5")) else {"temperature": 0.1}
    r = client.chat.completions.parse(
        model=CHAT_MODEL,
        **extra,
        messages=[{"role": "system", "content": SISTEMA},
                  {"role": "user", "content": USUARIO.format(empresa=empresa, sector=sector, fecha=fecha,
                                                              evidencia=evidencia)}],
        response_format=Informe,
    )
    informe, descartados = validar(r.choices[0].message.parsed, etiquetas)
    out.update(informe=informe, descartados=descartados, modelo=CHAT_MODEL)
    out["uso"].update(input_tokens=r.usage.prompt_tokens, output_tokens=r.usage.completion_tokens)
    out["uso"]["costo_usd"] = costo(out["uso"])
    return out


def costo(uso: dict) -> float | None:
    """Costo por informe con los precios que el founder configure en .env (US$ por millón de tokens).

    No se fijan precios en el código: cambian y deben verificarse en https://openai.com/api/pricing
    """
    try:
        p_in = float(os.environ["PRICE_INPUT_PER_1M"])
        p_out = float(os.environ["PRICE_OUTPUT_PER_1M"])
        p_emb = float(os.getenv("PRICE_EMBED_PER_1M", "0"))
    except (KeyError, ValueError):
        return None
    return round((uso["input_tokens"] * p_in + uso["output_tokens"] * p_out
                  + uso["embedding_tokens"] * p_emb) / 1e6, 5)
