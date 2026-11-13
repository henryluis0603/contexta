"""Estructuras de datos compartidas por la ingesta, el RAG y la app."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

# Las seis dimensiones del contexto que el analista suele no revisar.
DIMENSIONES = {
    "empresa": "Noticias sobre la propia empresa: inversiones, adquisiciones, resultados, financiamiento, litigios, reputación",
    "sector": "Situación y desempeño del sector económico: demanda, precios, producción, competencia",
    "macro": "Contexto macroeconómico peruano: crecimiento, inflación, tasa de referencia, tipo de cambio",
    "clima": "Factores climáticos y naturales: Fenómeno El Niño, lluvias, sequías, huaicos, temperatura del mar",
    "regulatorio": "Cambios regulatorios, tributarios o de política pública que afectan al sector o a la empresa",
    "social": "Conflictos sociales, paros, bloqueos, inseguridad, extorsión o tensión política que afectan la operación",
}


@dataclass
class Documento:
    """Una pieza de evidencia citable: una noticia o una serie del BCRP."""

    titulo: str
    fuente: str          # medio o institución (Gestión, BCRP, Andina...)
    url: str
    fecha: str           # ISO yyyy-mm-dd
    dimension: str       # una de DIMENSIONES
    texto: str
    tipo: str = "noticia"          # "noticia" | "serie_bcrp"
    verificada: bool = False       # fuente oficial o medio reconocido
    id: str = field(default="")

    def __post_init__(self):
        if not self.id:
            self.id = hashlib.sha1(self.url.encode()).hexdigest()[:10]

    def to_dict(self) -> dict:
        return asdict(self)
