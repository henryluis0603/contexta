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

# Consultas por dimensión. {e} = empresa, {s} = palabras del sector.
CONSULTAS = {
    "empresa": ['"{e}"'],
    "sector": ["sector {s} Perú"],
    "macro": ["economía peruana BCRP crecimiento inflación"],
    "clima": ["Fenómeno El Niño {s} Perú", "SENAMHI ENFEN lluvias {s}"],
    "regulatorio": ["{s} Perú nueva norma reglamento", "{s} Perú SUNAT impuesto", "{e} Indecopi OR SUNAT OR multa"],
    "social": ["{s} Perú paro transportistas bloqueo", "{s} Perú extorsión inseguridad", "{e} conflicto OR denuncia"],
}
PALABRAS_SECTOR = {
    "Agropecuario": "agroexportación agro", "Pesca": "pesca anchoveta", "Minería e hidrocarburos": "minería",
    "Manufactura": "manufactura industria", "Construcción": "construcción inmobiliario",
    "Comercio": "consumo masivo retail", "Electricidad y agua": "electricidad energía", "Servicios": "servicios",
}


def _dominio(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


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
        if not url or not clasificar(_dominio(url)):
            return None
        html = httpx.get(url, timeout=15, follow_redirects=True, headers=UA).text
        texto = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    except Exception:
        return None
    if len(texto) < 300:  # muro de pago, captcha o página caída
        return None
    return {**entrada, "url": url, "texto": texto[:6000]}


def documentos_noticias(empresa: str, sector: str, por_dimension: int = 6, dias: int = 120) -> list[Documento]:
    """Busca, filtra por fuente confiable y descarga el texto completo, en paralelo."""
    s = PALABRAS_SECTOR.get(sector, sector)
    candidatos: list[tuple[str, dict]] = []
    vistos: set[str] = set()
    for dim, plantillas in CONSULTAS.items():
        for p in plantillas:
            limite = por_dimension * 2 if dim == "empresa" else max(2, por_dimension // len(plantillas))
            try:
                for ent in buscar_rss(p.format(e=empresa, s=s), dias=dias, limite=limite):
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
