"""Búsqueda web: encuentra a las empresas que no salen en noticias (registros, gob.pe, directorios RUC).

Google News solo cubre medios; una pyme exportadora de Chimbote aparece en la consulta RUC replicada por
directorios, en resoluciones de PRODUCE o en su propia web. Dos proveedores:
  - OpenAI (por defecto): la herramienta web_search de la Responses API, con la MISMA OPENAI_API_KEY. Devuelve
    una síntesis con citas (url_citation); guardamos esa síntesis rotulada con la página que cita.
  - Tavily (opcional, si hay TAVILY_API_KEY): devuelve extractos de cada página; plan gratuito mensual.
Sin ninguna clave devuelve [] y el resto de Auditrail sigue funcionando.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import httpx

from backend.models import Documento

API = "https://api.tavily.com/search"
CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "web"
BLOQUEADOS = ("facebook.com", "instagram.com", "tiktok.com", "x.com", "twitter.com", "youtube.com",
              "linkedin.com", "pinterest.")


def _dominio(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def tipo_fuente(url: str) -> str:
    """'oficial' (gob.pe y similares), 'medio' o 'directorio' (webs que replican el padrón RUC, la web de la
    empresa, etc.). Los directorios se usan, pero se rotulan como tales para que el auditor los pondere."""
    from backend.sources.noticias import MEDIOS, OFICIALES

    d = _dominio(url)
    if any(d.endswith(o) for o in OFICIALES) or d.endswith(".gob.pe"):
        return "oficial"
    if any(d.endswith(m) for m in MEDIOS):
        return "medio"
    return "directorio"


def proveedor() -> str | None:
    if os.getenv("TAVILY_API_KEY"):
        return "tavily"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return None


def buscar_web(consulta: str, max_resultados: int = 8, profundidad: str = "advanced") -> list[dict]:
    """[{titulo, url, contenido, dominio, tipo}] con caché diaria. [] si no hay clave o falla."""
    prov = proveedor()
    if not prov:
        return []
    CACHE.mkdir(parents=True, exist_ok=True)
    clave_cache = f"{prov}|{consulta}" + (f"|{max_resultados}|{profundidad}" if prov == "tavily" else f"|{PROMPT_OPENAI}|v3")
    archivo = CACHE / f"{hashlib.sha1(clave_cache.encode()).hexdigest()[:16]}_{date.today().isoformat()}.json"
    if archivo.exists():
        return json.loads(archivo.read_text())
    out = _openai(consulta) if prov == "openai" else _tavily(consulta, max_resultados, profundidad)
    if out:
        archivo.write_text(json.dumps(out, ensure_ascii=False))
    return out


PROMPT_OPENAI = (
    "Busca en la web: {consulta}. Reporta los datos de identificación de esa empresa peruana que encuentres "
    "(razón social, nombre comercial, RUC, actividad económica y CIIU, estado y condición ante SUNAT, inicio de "
    "actividades, ubicación, escala u operaciones, habilitaciones, ventas o ingresos anuales más recientes con su "
    "año y moneda, y el grupo económico al que pertenece) y hechos recientes relevantes para su riesgo de crédito. Cita cada dato con la página de donde sale. No incluyas nombres de personas naturales. Si no "
    "encuentras la empresa, dilo y no inventes."
)


def _openai(consulta: str) -> list[dict]:
    """Responses API + web_search. Cada página citada se vuelve un resultado cuyo contenido es la síntesis."""
    from openai import OpenAI

    try:
        r = OpenAI().responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            tools=[{"type": "web_search", "user_location": {"type": "approximate", "country": "PE"}}],
            input=PROMPT_OPENAI.format(consulta=consulta))
    except Exception:
        return []
    texto = r.output_text.strip()
    urls_citadas: dict[str, tuple[str, str]] = {}  # url original (con utm) -> (url limpia, título)
    for o in r.output:
        for c in getattr(o, "content", None) or []:
            for a in getattr(c, "annotations", None) or []:
                if a.type == "url_citation":
                    limpia = a.url.replace("?utm_source=openai", "").replace("&utm_source=openai", "")
                    urls_citadas.setdefault(a.url, (limpia, a.title))
    paginas = asignar_parrafos(texto, urls_citadas)
    return [{"titulo": p["titulo"], "url": url, "dominio": _dominio(url), "tipo": tipo_fuente(url),
             "contenido": "Fragmento de búsqueda web (OpenAI) basado en esta página:\n"
                          + "\n".join(p["parrafos"])[:3000]}
            for url, p in paginas.items() if p["parrafos"] and not any(b in _dominio(url) for b in BLOQUEADOS)]


def asignar_parrafos(texto: str, urls_citadas: dict[str, tuple[str, str]]) -> dict[str, dict]:
    """Asigna cada párrafo de la síntesis a la(s) página(s) que lo respaldan.

    El modelo a veces cita al final de cada línea y a veces escribe un bloque de datos sin enlaces seguido de
    una línea que solo contiene la cita. Por eso los párrafos sin cita se acumulan y se asignan a la próxima
    línea con cita; si quedan al final sin cita posterior, van a la última cita vista.
    """
    paginas: dict[str, dict] = {}
    pendientes: list[str] = []
    ultimas: list[str] = []
    for x in (x.strip() for x in texto.split("\n")):
        if not x:
            continue
        citas = [u for u in urls_citadas if u in x]
        if not citas:
            pendientes.append(x)
            continue
        solo_cita = not re.sub(r"\(?\[[^\]]*\]\([^)]*\)\)?|[-–•*\s.,;:]", "", x)
        bloque = pendientes + ([] if solo_cita else [x])
        for u in citas:
            limpia, titulo = urls_citadas[u]
            pag = paginas.setdefault(limpia, {"titulo": titulo, "parrafos": []})
            pag["parrafos"] += [b for b in bloque if b not in pag["parrafos"]]
        pendientes, ultimas = [], citas
    for u in ultimas:
        limpia, _ = urls_citadas[u]
        paginas[limpia]["parrafos"] += [b for b in pendientes if b not in paginas[limpia]["parrafos"]]
    return paginas


def _tavily(consulta: str, max_resultados: int, profundidad: str) -> list[dict]:
    clave = os.getenv("TAVILY_API_KEY")
    try:
        r = httpx.post(API, timeout=30, headers={"Authorization": f"Bearer {clave}"},
                       json={"query": consulta, "search_depth": profundidad, "max_results": max_resultados,
                             "country": "peru", "include_answer": False})
        r.raise_for_status()
        resultados = r.json().get("results", [])
    except (httpx.HTTPError, ValueError):
        return []
    return [{"titulo": x.get("title", ""), "url": x["url"], "contenido": x.get("content", ""),
             "dominio": _dominio(x["url"]), "tipo": tipo_fuente(x["url"])}
            for x in resultados if x.get("url") and not any(b in _dominio(x["url"]) for b in BLOQUEADOS)]


def documentos_web(empresa: str) -> list[Documento]:
    """Evidencia de registro sobre la empresa (dimensión 'empresa'), para la ficha y para el RAG."""
    vistos, docs = set(), []
    consultas = [f'"{empresa}" RUC Perú actividad económica']
    if proveedor() == "tavily":  # con OpenAI una sola búsqueda basta (y cada una tiene costo)
        consultas.append(f'"{empresa}" Perú empresa')
    for consulta in consultas:
        for x in buscar_web(consulta):
            if x["url"] in vistos or len(x["contenido"]) < 80:
                continue
            vistos.add(x["url"])
            docs.append(Documento(titulo=x["titulo"] or x["dominio"], fuente=x["dominio"], url=x["url"],
                                  fecha=f"s/f (consultado {date.today().isoformat()})", dimension="empresa",
                                  texto=x["contenido"],
                                  tipo=f"web_{x['tipo']}", verificada=x["tipo"] != "directorio"))
    return docs
