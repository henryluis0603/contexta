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
from backend.models import DIMENSIONES, Documento

EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
CHAT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

Senal = Literal["favorable", "neutral", "desfavorable", "sin_evidencia"]


# ---------- Salida estructurada ----------
class Hallazgo(BaseModel):
    afirmacion: str = Field(description="Hecho concreto, con cifra y periodo si la evidencia los tiene")
    impacto: Literal["positivo", "negativo", "neutral"]
    fuentes: list[str] = Field(description='Etiquetas de la evidencia que lo respaldan, p. ej. ["S2", "S7"]')


class Dimension(BaseModel):
    nombre: Literal["empresa", "sector", "macro", "clima", "regulatorio", "social"]
    senal: Senal
    hallazgos: list[Hallazgo]


class Informe(BaseModel):
    resumen_ejecutivo: str = Field(description="3 a 4 oraciones para el comité de créditos")
    senal_global: Senal
    factores_explicativos: list[Hallazgo] = Field(description="Por qué le va bien o mal, más allá de los EEFF")
    dimensiones: list[Dimension]
    preguntas_para_el_cliente: list[str]
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

    def buscar(self, consulta: str, k: int = 6, preferir: str | None = None,
               bonus: float = 0.05) -> list[tuple[Fragmento, float]]:
        """Similitud coseno; `preferir` suma un bonus a los fragmentos cuya búsqueda de origen fue esa dimensión."""
        q = self.emb([consulta])[0]
        q = q / (np.linalg.norm(q) + 1e-9)
        s = self.m @ q
        if preferir:
            s = s + bonus * np.array([f.doc.dimension == preferir for f in self.frags])
        return [(self.frags[i], float(s[i])) for i in np.argsort(-s)[:k]]


# ---------- Recuperación por dimensión ----------
def recuperar(indice: Indice, empresa: str, sector: str, k: int = 5) -> dict[str, list[tuple[Fragmento, float]]]:
    """Una consulta por dimensión: así ninguna dimensión queda tapada por las noticias de la empresa."""
    return {dim: indice.buscar(f"{empresa} (sector {sector}). {desc}", k=k, preferir=dim)
            for dim, desc in DIMENSIONES.items()}


def armar_evidencia(recuperados: dict, docs: list[Documento]) -> tuple[str, dict[str, Documento]]:
    """Etiqueta cada documento como S1..Sn y arma el bloque de evidencia que verá el modelo.

    Las series del BCRP entran siempre: son cortas y son la base cuantitativa del informe.
    """
    por_doc: dict[str, list[str]] = {}
    for d in docs:
        if d.tipo == "serie_bcrp":
            por_doc.setdefault(d.id, []).append(d.texto)
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
        bloques.append(f"[{et}] {d.fuente} · {d.fecha} · {d.titulo}\n" + "\n…\n".join(textos))
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

    informe.factores_explicativos = limpiar(informe.factores_explicativos)
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
