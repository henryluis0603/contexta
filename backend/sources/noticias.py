"""Scraping de noticias (sesión 03): Google News RSS -> URL original -> texto completo del artículo.

Solo se conservan medios reconocidos y fuentes oficiales; redes sociales y agregadores quedan fuera.
"""
from __future__ import annotations

import concurrent.futures as cf
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urlparse

import feedparser
import httpx
import trafilatura

from backend.models import Documento
from backend.sources.bcrp import SUBSECTORES

RSS = "https://news.google.com/rss/search?q={q}&hl=es-419&gl=PE&ceid=PE:es-419"
UA = {"User-Agent": "Mozilla/5.0 (Contexta; research bot)"}

# Fuentes oficiales: se marcan como verificadas.
OFICIALES = ("gob.pe", "bcrp.gob.pe", "sbs.gob.pe", "smv.gob.pe", "inei.gob.pe", "senamhi.gob.pe",
             "andina.pe", "imarpe.gob.pe", "mef.gob.pe", "sunat.gob.pe", "elperuano.pe")
# Medios económicos y generalistas reconocidos.
MEDIOS = ("gestion.pe", "elcomercio.pe", "larepublica.pe", "rpp.pe", "semanaeconomica.com", "forbes.pe",
          "infobae.com", "bnamericas.com", "perueconomico.com", "expreso.com.pe", "peru21.pe",
          "lexlatin.com", "reuters.com", "bloomberglinea.com", "americaeconomia.com", "agraria.pe",
          "energiminas.com", "rumbominero.com", "mercadosyregiones.com", "elbuho.pe", "canaln.pe",
          "exitosanoticias.pe", "correo.pe", "larazon.pe", "noticias.yahoo.com", "swissinfo.ch",
          "efe.com", "europapress.es", "bloomberg.com", "ft.com")
BLOQUEADOS = ("facebook.com", "instagram.com", "tiktok.com", "x.com", "twitter.com", "youtube.com",
              "linkedin.com", "pinterest.")

# Consultas por dimensión. {e} = empresa, {s} = grupo de términos del sector, p. ej. (pesca OR anchoveta).
# Google News exige TODAS las palabras de una consulta: por eso las alternativas van con OR. Una consulta como
# "pesca anchoveta Perú paro transportistas bloqueo" devolvía 0 resultados y la dimensión quedaba sin fuentes.
CONSULTAS = {
    "empresa": ['"{e}"'],
    "sector": ["{s} Perú"],
    "macro": ["economía peruana BCRP crecimiento inflación"],
    "clima": ['{s} Perú ("El Niño" OR lluvias OR huaicos OR sequía OR SENAMHI OR ENFEN)'],
    "regulatorio": ["{s} Perú (norma OR decreto OR reglamento OR ley OR fiscalización)",
                    "{s} Perú (SUNAT OR impuesto OR multa OR tributario)", '"{e}" (Indecopi OR SUNAT OR multa)'],
    "social": ["{s} Perú (paro OR bloqueo OR huelga OR protesta OR conflicto)",
               "{s} Perú (extorsión OR inseguridad OR delincuencia)", '"{e}" (conflicto OR denuncia)'],
}
# Términos cortos por sector (se combinan con OR).
PALABRAS_SECTOR = {
    "Agropecuario": ["agro", "agroexportación", "agricultura"], "Pesca": ["pesca", "pesquero", "anchoveta"],
    "Minería e hidrocarburos": ["minería", "minera", "hidrocarburos"], "Manufactura": ["industria", "manufactura"],
    "Construcción": ["construcción", "inmobiliario"], "Comercio": ["comercio", "retail", '"consumo masivo"'],
    "Electricidad y agua": ["electricidad", "eléctrica", "energía"], "Servicios": ["servicios", "turismo", "transporte"],
}


def grupo(terminos: list[str]) -> str:
    """['pesca', 'anchoveta'] -> '(pesca OR anchoveta)'."""
    return terminos[0] if len(terminos) == 1 else "(" + " OR ".join(terminos) + ")"


def _dominio(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


# Secciones de otros países en medios regionales (p. ej. infobae.com/colombia/...): no son contexto peruano.
OTROS_PAISES = ("argentina", "colombia", "mexico", "chile", "venezuela", "ecuador", "bolivia", "uruguay",
                "paraguay", "espana", "estados-unidos", "centroamerica")


def es_de_otro_pais(url: str) -> bool:
    """True si la primera carpeta de la URL es la sección de otro país."""
    partes = [p for p in urlparse(url).path.lower().split("/") if p]
    return bool(partes) and partes[0] in OTROS_PAISES


def clasificar(dominio: str) -> str | None:
    """'oficial', 'medio' o None (descartar)."""
    if any(b in dominio for b in BLOQUEADOS):
        return None
    if any(dominio.endswith(o) for o in OFICIALES):
        return "oficial"
    if any(dominio.endswith(m) for m in MEDIOS):
        return "medio"
    return None


def buscar_rss(consulta: str, dias: int = 120, limite: int = 15) -> list[dict]:
    """Entradas de Google News: título, medio, fecha y enlace (aún codificado)."""
    r = httpx.get(RSS.format(q=quote_plus(f"{consulta} when:{dias}d")), timeout=20, headers=UA)
    entradas = []
    for e in feedparser.parse(r.text).entries:
        medio_url = e.get("source", {}).get("href", "")
        tipo = clasificar(_dominio(medio_url))
        if not tipo:
            continue
        try:
            fecha = parsedate_to_datetime(e.published).date().isoformat()
        except Exception:
            fecha = datetime.now().date().isoformat()
        titulo = e.title.rsplit(" - ", 1)[0]
        entradas.append({"titulo": titulo, "medio": e.get("source", {}).get("title", ""), "link": e.link,
                         "fecha": fecha, "tipo": tipo})
        if len(entradas) >= limite:
            break
    return entradas


def _resolver_y_leer(entrada: dict) -> dict | None:
    """Decodifica el enlace de Google News y extrae el texto del artículo original."""
    from googlenewsdecoder import gnewsdecoder

    try:
        url = gnewsdecoder(entrada["link"], interval=0).get("decoded_url")
        if not url or not clasificar(_dominio(url)) or es_de_otro_pais(url):
            return None
        html = httpx.get(url, timeout=15, follow_redirects=True, headers=UA).text
        texto = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    except Exception:
        return None
    if len(texto) < 300:  # muro de pago, captcha o página caída
        return None
    return {**entrada, "url": url, "texto": texto[:6000]}


def documentos_noticias(empresa: str, sector: str, por_dimension: int = 6, dias: int = 120,
                        subsector: str | None = None) -> list[Documento]:
    """Busca, filtra por fuente confiable y descarga el texto completo, en paralelo.

    Si hay subsector, se busca con sus palabras clave ("minería cobre oro", más pertinente) Y con las del sector
    general ("minería"): las palabras del subsector solas pueden ser tan específicas que Google News no devuelva
    nada (p. ej. normas o paros de "pesca pota perico"), y la dimensión quedaría sin evidencia.
    """
    general = grupo(PALABRAS_SECTOR.get(sector, [sector.lower()]))
    terminos_sub = SUBSECTORES.get(sector, {}).get(subsector or "", {}).get("palabras")
    especifico = grupo(terminos_sub) if terminos_sub else None
    variantes = [especifico, general] if especifico else [general]
    candidatos: list[tuple[str, dict]] = []
    vistos: set[str] = set()
    for dim, plantillas in CONSULTAS.items():
        consultas = list(dict.fromkeys(p.format(e=empresa, s=s) for p in plantillas for s in variantes))
        for consulta in consultas:
            limite = por_dimension * 2 if dim == "empresa" else max(2, por_dimension // len(consultas) + 1)
            try:
                for ent in buscar_rss(consulta, dias=dias, limite=limite):
                    if ent["titulo"] not in vistos:
                        vistos.add(ent["titulo"])
                        candidatos.append((dim, ent))
            except httpx.HTTPError:
                continue

    docs: list[Documento] = []
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        futuros = {pool.submit(_resolver_y_leer, ent): dim for dim, ent in candidatos}
        for f in cf.as_completed(futuros):
            r = f.result()
            if r:
                docs.append(Documento(titulo=r["titulo"], fuente=r["medio"], url=r["url"], fecha=r["fecha"],
                                      dimension=futuros[f], texto=r["texto"], verificada=True,
                                      tipo="noticia_oficial" if r["tipo"] == "oficial" else "noticia"))
    docs.sort(key=lambda d: d.fecha, reverse=True)
    return docs
