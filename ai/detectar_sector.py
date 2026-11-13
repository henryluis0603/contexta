"""Detecta el sector y subsector de una empresa a partir de sus titulares recientes (salida estructurada).

No usa la memoria del modelo: le pasamos titulares de Google News y debe elegir del catálogo de
backend/sources/bcrp.py, citando el titular que lo justifica. Si no hay evidencia, lo dice (confianza "baja").
"""
from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field

from backend.sources.bcrp import SUBSECTORES
from backend.sources.noticias import buscar_rss
from backend.sources.web import buscar_web

CHAT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
# "Sector › Subsector": así el esquema estricto solo admite combinaciones válidas del catálogo.
OPCIONES = [f"{s} › {sub}" for s, subs in SUBSECTORES.items() for sub in subs]


class Deteccion(BaseModel):
    clasificacion: Literal[tuple(OPCIONES)]  # type: ignore[valid-type]
    actividad: str = Field(description="A qué se dedica la empresa, en una frase, según los titulares")
    titular_clave: int = Field(description="Número del titular que mejor lo justifica; 0 si ninguno")
    confianza: Literal["alta", "media", "baja"]

    @property
    def sector(self) -> str:
        return self.clasificacion.split(" › ")[0]

    @property
    def subsector(self) -> str:
        return self.clasificacion.split(" › ", 1)[1]


def detectar_sector(empresa: str, api_key: str | None = None) -> dict | None:
    """Devuelve {sector, subsector, actividad, confianza, titular, url} o None si no hay API key o falla."""
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not api_key or not empresa.strip():
        return None
    try:
        titulares = buscar_rss(f'"{empresa}" Perú', dias=365, limite=12)
    except Exception:
        titulares = []
    # Las pymes no salen en noticias: sumamos resultados web (registros RUC, gob.pe) si hay TAVILY_API_KEY.
    # Misma consulta que documentos_web: la segunda vez sale de la caché (una sola búsqueda por empresa).
    for w in buscar_web(f'"{empresa}" RUC Perú actividad económica')[:6]:
        titulares.append({"titulo": f"{w['titulo']} — {w['contenido'][:600]}", "medio": w["dominio"],
                          "fecha": "web"})
    lista = "\n".join(f"{i}. {t['titulo']} ({t['medio']}, {t['fecha']})" for i, t in enumerate(titulares, 1))

    from openai import OpenAI

    try:
        r = OpenAI(api_key=api_key).chat.completions.parse(
            model=CHAT_MODEL,
            **({} if CHAT_MODEL.startswith(("o", "gpt-5")) else {"temperature": 0}),
            messages=[
                {"role": "system", "content":
                    "Clasificas empresas peruanas en el sector y subsector económico de su actividad PRINCIPAL: la que "
                    "genera la mayor parte de sus ingresos, no la de una adquisición o un proyecto reciente. "
                    "Básate SOLO en los titulares y resultados web dados. Si los titulares no permiten saber a qué se dedica la "
                    "empresa, elige la opción más probable, usa titular_clave 0 y confianza 'baja'."},
                {"role": "user", "content": f"Empresa: {empresa}\n\nTitulares y resultados web:\n{lista or '(ninguno)'}"},
            ],
            response_format=Deteccion,
        )
        d: Deteccion = r.choices[0].message.parsed
    except Exception:
        return None
    t = titulares[d.titular_clave - 1] if 0 < d.titular_clave <= len(titulares) else None
    return {"sector": d.sector, "subsector": d.subsector, "actividad": d.actividad,
            "confianza": "baja" if t is None else d.confianza,
            "titular": t["titulo"].split(" — ")[0] if t else None, "medio": t["medio"] if t else None}
