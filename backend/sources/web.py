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


def buscar_web(consulta: str, max_resultados: int = 8, profundidad: str = "advanced",
               prompt: str | None = None) -> list[dict]:
    """[{titulo, url, contenido, dominio, tipo}] con caché diaria. [] si no hay clave o falla.

    `prompt` (solo OpenAI) indica qué reportar de la búsqueda; por defecto, la ficha de la empresa."""
    prompt = prompt or PROMPT_OPENAI
    prov = proveedor()
    if not prov:
        return []
    CACHE.mkdir(parents=True, exist_ok=True)
    clave_cache = f"{prov}|{consulta}" + (f"|{max_resultados}|{profundidad}" if prov == "tavily" else f"|{prompt}|v4")
    archivo = CACHE / f"{hashlib.sha1(clave_cache.encode()).hexdigest()[:16]}_{date.today().isoformat()}.json"
    if archivo.exists():
        return json.loads(archivo.read_text())
    out = _openai(consulta, prompt) if prov == "openai" else _tavily(consulta, max_resultados, profundidad)
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


PROMPT_GRUPO = (
    "Busca en la web: {consulta}. Identifica si esa empresa peruana pertenece a un grupo económico o holding: su "
    "matriz o accionista controlador (si es una persona jurídica), sus subsidiarias y las principales empresas "
    "vinculadas, con el tipo de relación (matriz, subsidiaria, misma matriz, participación de X %). Luego, para el "
    "grupo y esas empresas, reporta hechos de los últimos 24 meses relevantes para su riesgo de crédito: "
    "resultados, endeudamiento, emisiones o refinanciamientos, reestructuraciones, ventas de activos, litigios, "
    "rating. Cita cada dato con la página de donde sale. No incluyas nombres de personas naturales. Si no "
    "encuentras un grupo económico, dilo y no inventes."
)

PROMPT_MERCADO = (
    "Busca en la web: {consulta}. Para esa empresa peruana reporta, con fecha: (1) la clasificación de riesgo MÁS "
    "RECIENTE de cada clasificadora (Moody's Local Perú, Apoyo & Asociados/Fitch, PCR, JCR, Class & Asociados, S&P, "
    "Fitch, Moody's) con el instrumento, la categoría, la perspectiva y los fundamentos que da la clasificadora (principales fortalezas y riesgos), y cualquier cambio de categoría o perspectiva "
    "en los últimos 24 meses; (2) hechos de importancia comunicados a la SMV en los últimos 12 meses (OPA, fusiones, "
    "adquisiciones, emisiones o recompras de bonos, cambios de control, dividendos, refinanciamientos); (3) "
    "proyectos de inversión o expansión anunciados. Prioriza smv.gob.pe, la web de la clasificadora y medios "
    "económicos. Cita cada dato con la página de donde sale. No incluyas nombres de personas naturales. Si no "
    "encuentras nada en una categoría, dilo y no inventes."
)

PROMPT_CUMPLIMIENTO = (
    "Busca en la web: {consulta}. Para esa empresa peruana reporta, con fecha: (1) sanciones o multas de OEFA, "
    "INDECOPI, SUNAFIL, SUNAT, OSINERGMIN, PRODUCE, SUNASS, OSIPTEL u otros reguladores; (2) procesos concursales en "
    "INDECOPI, procesos judiciales o arbitrales relevantes; (3) conflictos sociales o ambientales que la involucren "
    "(Defensoría del Pueblo, comunidades, derrames, paralizaciones); (4) investigaciones fiscales, casos de "
    "corrupción, lavado de activos o inclusión en listas de sanciones. Distingue investigación o denuncia de sanción "
    "firme. Cita cada dato con la página de donde sale. No incluyas nombres de personas naturales. Si no encuentras "
    "nada en una categoría, dilo y no inventes."
)


REGLA_CIFRAS = ("Copia montos y cifras tal como aparecen, con el texto entre paréntesis que los expresa en letras: en "
                "Perú la coma suele ser decimal (\"7,252 (siete con 252/1000) UIT\" son 7.252 UIT, no 7 mil). "
                "Indica la fecha de cada dato.")


def _openai(consulta: str, prompt: str = PROMPT_OPENAI) -> list[dict]:
    """Responses API + web_search. Cada página citada se vuelve un resultado cuyo contenido es la síntesis."""
    from openai import OpenAI

    try:
        r = OpenAI().responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            tools=[{"type": "web_search", "user_location": {"type": "approximate", "country": "PE"}}],
            input=prompt.format(consulta=consulta) + " " + REGLA_CIFRAS)
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


def documentos_web_riesgo(empresa: str) -> list[Documento]:
    """Grupo económico (riesgo único) y señales externas y alertas (mercado y cumplimiento): 3 búsquedas web."""
    vistos, docs = set(), []
    busquedas = [("grupo", f'"{empresa}" Perú grupo económico empresas vinculadas', PROMPT_GRUPO),
                 ("alertas", f'"{empresa}" Perú clasificación de riesgo, hechos de importancia SMV, proyectos',
                  PROMPT_MERCADO),
                 ("alertas", f'"{empresa}" Perú sanciones, multas, procesos judiciales, conflictos', PROMPT_CUMPLIMIENTO)]
    for dimension, consulta, prompt in busquedas:
        for x in buscar_web(consulta, prompt=prompt):
            if (dimension, x["url"]) in vistos or len(x["contenido"]) < 80:
                continue
            vistos.add((dimension, x["url"]))
            docs.append(Documento(titulo=x["titulo"] or x["dominio"], fuente=x["dominio"], url=x["url"],
                                  fecha=f"s/f (consultado {date.today().isoformat()})", dimension=dimension,
                                  texto=x["contenido"], tipo=f"web_{x['tipo']}",
                                  verificada=x["tipo"] != "directorio", id=f"{dimension}-" + hashlib.sha1(
                                      x["url"].encode()).hexdigest()[:10]))
    return docs


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
