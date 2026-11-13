"""Cliente de la API de series del BCRP (misma API que el servidor MCP de la sesión 04).

Las cuentas las hace Python, no el modelo: cada cifra del informe sale de una llamada
reproducible a https://estadisticas.bcrp.gob.pe/estadisticas/series/api
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import httpx

from backend.models import Documento

API = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api"
WEB = "https://estadisticas.bcrp.gob.pe/estadisticas/series/mensuales/resultados/{codigo}/html"
CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "bcrp"

MESES = {"Ene": 1, "Feb": 2, "Mar": 3, "Abr": 4, "May": 5, "Jun": 6, "Jul": 7,
         "Ago": 8, "Set": 9, "Sep": 9, "Oct": 10, "Nov": 11, "Dic": 12}

# Series macro comunes a todas las empresas (códigos verificados en el catálogo del BCRP).
MACRO = {
    "PN01728AM": ("PBI (var. % interanual)", "%"),
    "PN01273PM": ("Inflación Lima Metropolitana, IPC (var. % 12 meses)", "%"),
    "PD04722MM": ("Tasa de referencia de la política monetaria", "%"),
    "PN01207PM": ("Tipo de cambio interbancario promedio (S/ por US$)", "S/"),
    "PD12912AM": ("Expectativa de inflación a 12 meses", "%"),
}

# Sector -> series propias del sector: PBI sectorial y, cuando existe, expectativas empresariales.
SECTORES = {
    "Agropecuario": {"PN01713AM": ("PBI Agropecuario (var. % interanual)", "%")},
    "Pesca": {"PN01716AM": ("PBI Pesca (var. % interanual)", "%"),
              "PN01649XM": ("Cotización internacional harina de pescado", "US$/tm")},
    "Minería e hidrocarburos": {"PN01717AM": ("PBI Minería e Hidrocarburos (var. % interanual)", "%"),
                                "PD39755AM": ("Expectativas del sector a 3 meses - Minería", "pts")},
    "Manufactura": {"PN01720AM": ("PBI Manufactura (var. % interanual)", "%"),
                    "PN01722AM": ("PBI Manufactura no primaria (var. % interanual)", "%"),
                    "PD39764AM": ("Expectativas del sector a 3 meses - Manufactura", "pts")},
    "Construcción": {"PN01724AM": ("PBI Construcción (var. % interanual)", "%"),
                     "PD39773AM": ("Expectativas del sector a 3 meses - Construcción", "pts")},
    "Comercio": {"PN01725AM": ("PBI Comercio (var. % interanual)", "%"),
                 "PD39782AM": ("Expectativas del sector a 3 meses - Comercio", "pts")},
    "Electricidad y agua": {"PN01723AM": ("PBI Electricidad y Agua (var. % interanual)", "%")},
    "Servicios": {"PN01726AM": ("PBI Otros Servicios (var. % interanual)", "%")},
}

# Subsectores: afinan las búsquedas de noticias ("palabras") y, cuando el BCRP publica la serie del
# subsector, la agregan ("series"). Códigos verificados en la API del BCRP el 2026-11-13.
_AGRICOLA = {"PN01714AM": ("PBI Agrícola (var. % interanual)", "%")}
_PECUARIO = {"PN01715AM": ("PBI Pecuario (var. % interanual)", "%")}
_MIN_METALICA = {"PN01718AM": ("PBI Minería metálica (var. % interanual)", "%")}
_HIDROCARBUROS = {"PN01719AM": ("PBI Hidrocarburos (var. % interanual)", "%")}
_MANUF_PRIMARIA = {"PN01721AM": ("PBI Manufactura de procesadores de recursos primarios (var. % interanual)", "%")}

SUBSECTORES: dict[str, dict[str, dict]] = {
    "Agropecuario": {
        "Agroexportación (frutas y hortalizas)": {"palabras": ["agroexportación", "arándanos", "palta", "uva"], "series": _AGRICOLA},
        "Agrícola para mercado interno (arroz, papa, azúcar)": {"palabras": ["arroz", "papa", '"caña de azúcar"', "agricultura"],
                                                                "series": _AGRICOLA},
        "Pecuario y avícola": {"palabras": ["avícola", "pollo", "ganadería", '"producción de leche"'], "series": _PECUARIO},
    },
    "Pesca": {
        "Harina y aceite de pescado": {"palabras": ["anchoveta", '"harina de pescado"', '"pesca industrial"'], "series": {}},
        "Pesca para consumo humano": {"palabras": ['"pesca artesanal"', '"consumo humano directo"', "pota", "perico", '"desembarque pesquero"'], "series": {}},
    },
    "Minería e hidrocarburos": {
        "Minería metálica (cobre, oro, zinc, plata)": {"palabras": ["cobre", "oro", "zinc", '"minería metálica"'], "series": _MIN_METALICA},
        "Hidrocarburos (petróleo y gas)": {"palabras": ["petróleo", '"gas natural"', "hidrocarburos"], "series": _HIDROCARBUROS},
    },
    "Manufactura": {
        "Procesadores de recursos primarios (harina de pescado, azúcar, refinación)": {
            "palabras": ['"harina de pescado"', "azúcar", "refinación", '"manufactura primaria"'], "series": _MANUF_PRIMARIA},
        "Consumo masivo (alimentos, bebidas, higiene)": {"palabras": ['"consumo masivo"', "alimentos", "bebidas", '"industria alimentaria"'], "series": {}},
        "Materiales de construcción e insumos industriales": {"palabras": ["cemento", "acero", '"insumos industriales"'],
                                                              "series": {}},
        "Textil y confecciones": {"palabras": ["textil", "confecciones"], "series": {}},
        "Química, plásticos y farmacéutica": {"palabras": ['"industria química"', "plásticos", "farmacéutica"], "series": {}},
    },
    "Construcción": {
        "Infraestructura y obra pública": {"palabras": ["infraestructura", '"obras públicas"', '"inversión pública"'], "series": {}},
        "Inmobiliario y vivienda": {"palabras": ["inmobiliario", "vivienda", "Mivivienda"], "series": {}},
        "Cemento y materiales": {"palabras": ["cemento", '"despacho de cemento"'], "series": {}},
    },
    "Comercio": {
        "Retail y supermercados": {"palabras": ["retail", "supermercados", '"centros comerciales"'], "series": {}},
        "Maquinaria y bienes de capital": {"palabras": ["maquinaria", '"bienes de capital"'], "series": {}},
        "Automotriz": {"palabras": ['"venta de vehículos"', "automotriz"], "series": {}},
        "Distribución mayorista": {"palabras": ['"distribución mayorista"', "mayoristas", '"consumo masivo"'], "series": {}},
    },
    "Electricidad y agua": {
        "Generación eléctrica": {"palabras": ['"generación eléctrica"', "hidroeléctrica", "COES"], "series": {}},
        "Transmisión y distribución eléctrica": {"palabras": ['"distribución eléctrica"', '"tarifas eléctricas"', "Osinergmin"],
                                                 "series": {}},
        "Agua y saneamiento": {"palabras": ["agua", "saneamiento", "Sunass"], "series": {}},
    },
    "Servicios": {
        "Transporte y logística": {"palabras": ["transporte", "logística", "puertos"], "series": {}},
        "Telecomunicaciones": {"palabras": ["telecomunicaciones", "telefonía", "Osiptel"], "series": {}},
        "Turismo, hoteles y restaurantes": {"palabras": ["turismo", "hoteles", "restaurantes"], "series": {}},
        "Salud y educación privada": {"palabras": ["clínicas", '"salud privada"', '"educación privada"'], "series": {}},
        "Servicios a empresas e inmobiliarios": {"palabras": ['"servicios empresariales"', "oficinas", "outsourcing"], "series": {}},
    },
}


def _periodo(nombre: str) -> str:
    """'Ago.2026' -> '2026-08'."""
    mes, anio = nombre.split(".")
    return f"{anio}-{MESES[mes]:02d}"


def serie(codigo: str, desde: str | None = None, hasta: str | None = None, reintentos: int = 3) -> dict:
    """Descarga una serie mensual. Devuelve {codigo, nombre, datos: [{periodo, valor}], url}.

    Guarda en caché por día: la API corta si recibe muchos pedidos seguidos.
    """
    hoy = date.today()
    desde = desde or f"{hoy.year - 2}-1"
    hasta = hasta or f"{hoy.year}-12"
    CACHE.mkdir(parents=True, exist_ok=True)
    archivo = CACHE / f"{codigo}_{desde}_{hasta}_{hoy.isoformat()}.json"
    if archivo.exists():
        return json.loads(archivo.read_text())

    url = f"{API}/{codigo}/json/{desde}/{hasta}"
    for intento in range(reintentos):
        r = httpx.get(url, timeout=30, headers={"User-Agent": "Contexta/0.1"})
        try:
            d = r.json()
            break
        except json.JSONDecodeError:  # la API devuelve HTML cuando la saturan
            time.sleep(2 * (intento + 1))
    else:
        raise RuntimeError(f"El BCRP no respondió JSON para {codigo}")

    datos = []
    for p in d.get("periods", []):
        v = p["values"][0]
        if v not in ("n.d.", "", None):
            datos.append({"periodo": _periodo(p["name"]), "valor": round(float(v), 2)})
    out = {"codigo": codigo, "nombre": d["config"]["series"][0]["name"], "datos": datos,
           "url": WEB.format(codigo=codigo)}
    archivo.write_text(json.dumps(out, ensure_ascii=False))
    return out


def resumen(s: dict) -> dict:
    """Estadísticos que el modelo nunca debe calcular a mano."""
    v = [d["valor"] for d in s["datos"]]
    if not v:
        return {}
    ult12 = s["datos"][-12:]
    return {
        "ultimo": s["datos"][-1],
        "hace_12m": s["datos"][-13] if len(v) >= 13 else s["datos"][0],
        "promedio_12m": round(sum(d["valor"] for d in ult12) / len(ult12), 2),
        "max_12m": max(ult12, key=lambda d: d["valor"]),
        "min_12m": min(ult12, key=lambda d: d["valor"]),
    }


def _a_documento(codigo: str, etiqueta: str, unidad: str, dimension: str) -> tuple[Documento, dict] | None:
    try:
        s = serie(codigo)
    except Exception:
        return None
    r = resumen(s)
    if not r:
        return None
    u = r["ultimo"]
    ult6 = ", ".join(f"{d['periodo']}: {d['valor']}" for d in s["datos"][-6:])
    texto = (
        f"Serie oficial del BCRP {codigo} — {etiqueta}. Último dato {u['periodo']}: {u['valor']} {unidad}. "
        f"Hace 12 meses ({r['hace_12m']['periodo']}): {r['hace_12m']['valor']} {unidad}. "
        f"Promedio de los últimos 12 meses: {r['promedio_12m']} {unidad}; "
        f"máximo {r['max_12m']['valor']} ({r['max_12m']['periodo']}), mínimo {r['min_12m']['valor']} ({r['min_12m']['periodo']}). "
        f"Últimos seis datos: {ult6}."
    )
    doc = Documento(titulo=f"BCRP · {etiqueta}", fuente="BCRP", url=s["url"], fecha=u["periodo"] + "-01",
                    dimension=dimension, texto=texto, tipo="serie_bcrp", verificada=True, id=f"BCRP-{codigo}")
    return doc, {"codigo": codigo, "etiqueta": etiqueta, "unidad": unidad, "datos": s["datos"]}


def documentos_bcrp(sector: str, subsector: str | None = None) -> tuple[list[Documento], list[dict]]:
    """Evidencia macro + sectorial (+ subsectorial si existe la serie) para el RAG, y las series para graficar."""
    docs, series = [], []
    propias = {**SECTORES.get(sector, {}), **SUBSECTORES.get(sector, {}).get(subsector or "", {}).get("series", {})}
    pedidos = [(c, *v, "macro") for c, v in MACRO.items()]
    pedidos += [(c, *v, "sector") for c, v in propias.items()]
    for codigo, etiqueta, unidad, dim in pedidos:
        r = _a_documento(codigo, etiqueta, unidad, dim)
        if r:
            docs.append(r[0])
            series.append(r[1])
    return docs, series
