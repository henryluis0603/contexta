"""Servidor MCP de Auditrail (sesión 04): el mismo motor, usable desde Claude Desktop / Claude Code.

    python mcp_server/server.py                                       # por stdio
    claude mcp add --scope project auditrail -- python mcp_server/server.py

El analista le pregunta a Claude "¿cómo está el contexto de Cementos Pacasmayo?" y Claude llama a
estas herramientas; cada cifra viene de una llamada reproducible al BCRP o de una noticia con URL.
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv  # noqa: E402
from fastmcp import FastMCP  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402

load_dotenv(RAIZ / ".env")

from ai.detectar_sector import detectar_sector  # noqa: E402
from ai.rag import analizar  # noqa: E402
from backend.recolector import recolectar  # noqa: E402
from backend.sources import bcrp  # noqa: E402
from backend.sources.noticias import documentos_noticias  # noqa: E402

SOLO_LECTURA = {"readOnlyHint": True, "openWorldHint": True}

mcp = FastMCP("auditrail", instructions=(
    "Contexto externo (macro, sector, clima, regulación, social, noticias) de empresas peruanas para análisis "
    "de crédito. Usa contexto_empresa para el informe completo. Cita siempre la etiqueta y la URL de la fuente; "
    "no inventes cifras: las series del BCRP ya vienen calculadas."))


@mcp.tool(annotations=SOLO_LECTURA)
def sectores_disponibles() -> dict[str, list[str]]:
    """Sectores válidos (clasificación del BCRP) y sus subsectores, para los demás tools."""
    return {s: list(subs) for s, subs in bcrp.SUBSECTORES.items()}


@mcp.tool(annotations=SOLO_LECTURA)
def detectar_sector_empresa(empresa: str) -> dict:
    """Detecta sector y subsector de una empresa a partir de sus titulares recientes, con el titular que lo
    justifica y la confianza. Úsalo antes de contexto_empresa si el usuario no dio el sector."""
    det = detectar_sector(empresa)
    if det is None:
        raise ToolError("No se pudo detectar (falta OPENAI_API_KEY o no hubo respuesta).")
    return det


@mcp.tool(annotations=SOLO_LECTURA)
def contexto_empresa(empresa: str, sector: str, subsector: str | None = None, refrescar: bool = False) -> dict:
    """Informe de contexto crediticio con citas: factores explicativos, señal por dimensión,
    puntos de verificación para la auditoría de la clasificación y la lista de fuentes (etiqueta -> medio, fecha, título, URL).

    empresa: razón social o nombre comercial, p. ej. "Alicorp". sector y subsector: de sectores_disponibles()
    (o de detectar_sector_empresa).
    """
    if sector not in bcrp.SECTORES:
        raise ToolError(f"Sector inválido {sector!r}. Opciones: {list(bcrp.SECTORES)}")
    if subsector and subsector not in bcrp.SUBSECTORES[sector]:
        raise ToolError(f"Subsector inválido {subsector!r}. Opciones: {list(bcrp.SUBSECTORES[sector])}")
    datos = recolectar(empresa, sector, usar_cache=not refrescar, subsector=subsector)
    etiqueta = f"{sector} › {subsector}" if subsector else sector
    res = analizar(empresa, etiqueta, datos["documentos"], datos["fecha"])
    fuentes = {k: {"fuente": d.fuente, "fecha": d.fecha, "titulo": d.titulo, "url": d.url}
               for k, d in res["etiquetas"].items()}
    if res["informe"] is None:
        return {"aviso": "Sin OPENAI_API_KEY: solo evidencia recuperada.", "fuentes": fuentes}
    return {"informe": res["informe"].model_dump(), "fuentes": fuentes, "uso": res["uso"]}


@mcp.tool(annotations=SOLO_LECTURA)
def indicadores_sector(sector: str) -> list[dict]:
    """Series oficiales del BCRP (macro + sector) con su resumen: último dato, hace 12 meses, promedio,
    máximo y mínimo de 12 meses, y la URL de la serie."""
    if sector not in bcrp.SECTORES:
        raise ToolError(f"Sector inválido {sector!r}. Opciones: {list(bcrp.SECTORES)}")
    docs, series = bcrp.documentos_bcrp(sector)
    return [{"codigo": s["codigo"], "serie": s["etiqueta"], "unidad": s["unidad"],
             **bcrp.resumen({"datos": s["datos"]}), "url": d.url} for s, d in zip(series, docs)]


@mcp.tool(annotations=SOLO_LECTURA)
def noticias_empresa(empresa: str, sector: str, dias: int = 90) -> list[dict]:
    """Noticias recientes de medios reconocidos y fuentes oficiales, clasificadas por dimensión de riesgo."""
    docs = documentos_noticias(empresa, sector, dias=dias)
    return [{"dimension": d.dimension, "fecha": d.fecha, "fuente": d.fuente, "titulo": d.titulo, "url": d.url,
             "extracto": d.texto[:500]} for d in docs]


@mcp.prompt()
def revision_clasificacion(empresa: str, sector: str) -> str:
    """Prepara el papel de trabajo de contexto externo para auditar la clasificación del deudor."""
    return (f"Usa contexto_empresa(empresa='{empresa}', sector='{sector}') y redacta la sección 'Entorno y "
            "riesgos externos' del papel de trabajo de auditoría de la clasificación del deudor "
            "(Res. SBS N.° 11356-2008), con los puntos a verificar en el expediente. Cada afirmación con su "
            "fuente [Sx] y URL.")


if __name__ == "__main__":
    mcp.run()
