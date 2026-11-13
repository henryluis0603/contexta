"""Junta toda la evidencia de una empresa: noticias (scraping) + series del BCRP (API).

Guarda el resultado en data/cache/ para que la demo responda en segundos y funcione
aunque falle internet (plan B).
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

from backend.models import Documento
from backend.sources.bcrp import documentos_bcrp
from backend.sources.noticias import documentos_noticias
from backend.sources.web import documentos_web

CACHE = Path(__file__).resolve().parents[1] / "data" / "cache"


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def recolectar(empresa: str, sector: str, usar_cache: bool = True, dias: int = 120,
               subsector: str | None = None) -> dict:
    """Devuelve {empresa, sector, subsector, fecha, documentos: [Documento], series: [...]}."""
    archivo = CACHE / ("_".join(_slug(x) for x in (empresa, sector, subsector or "") if x) + ".json")
    if usar_cache and archivo.exists():
        d = json.loads(archivo.read_text())
        d["documentos"] = [Documento(**x) for x in d["documentos"]]
        d["desde_cache"] = True
        return d

    docs_bcrp, series = documentos_bcrp(sector, subsector)
    docs_news = documentos_noticias(empresa, sector, dias=dias, subsector=subsector)
    docs_news += documentos_web(empresa)  # registros y webs: clave para empresas que no salen en noticias
    resultado = {"empresa": empresa, "sector": sector, "subsector": subsector, "fecha": date.today().isoformat(),
                 "documentos": docs_news + docs_bcrp, "series": series}

    CACHE.mkdir(parents=True, exist_ok=True)
    archivo.write_text(json.dumps({**resultado, "documentos": [d.to_dict() for d in resultado["documentos"]]},
                                  ensure_ascii=False, indent=1))
    resultado["desde_cache"] = False
    return resultado
