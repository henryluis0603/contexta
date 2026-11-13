"""Pruebas sin internet ni API key: fragmentación, recuperación y validación de citas."""
from ai.rag import (Dimension, EmbedderTFIDF, Hallazgo, Indice, Informe, armar_evidencia, fragmentar, recuperar,
                    validar)
from backend.models import Documento
from backend.sources.bcrp import _periodo, resumen
from backend.sources.noticias import clasificar

DOCS = [
    Documento("Alicorp compra Flora Food", "Gestión", "https://gestion.pe/a", "2026-11-02", "empresa",
              "Alicorp adquirió Flora Food por US$150 millones.\n" * 30),
    Documento("El Niño costero reduce la pesca", "Andina", "https://andina.pe/b", "2026-10-01", "clima",
              "El ENFEN mantiene la alerta de El Niño costero; lluvias en el norte."),
    Documento("BCRP · PBI", "BCRP", "https://bcrp", "2026-08-01", "macro", "PBI creció 3.2%.",
              tipo="serie_bcrp", verificada=True, id="BCRP-PN01728AM"),
]


def test_fragmentar_respeta_tamano():
    frags = fragmentar(DOCS, tam=300, solape=50)
    assert len(frags) > 3
    assert all(len(f.texto) <= 300 + 60 for f in frags)


def test_recuperacion_encuentra_la_dimension_correcta():
    idx = Indice(fragmentar(DOCS), EmbedderTFIDF())
    rec = recuperar(idx, "Alicorp", "Comercio", k=2)
    assert rec["clima"][0][0].doc.dimension == "clima"


def test_bcrp_siempre_entra_en_la_evidencia():
    idx = Indice(fragmentar(DOCS), EmbedderTFIDF())
    _, etiquetas = armar_evidencia(recuperar(idx, "Alicorp", "Comercio", k=1), DOCS)
    assert any(d.id == "BCRP-PN01728AM" for d in etiquetas.values())


def test_validar_elimina_citas_inventadas():
    inf = Informe(
        resumen_ejecutivo="x", senal_global="neutral",
        factores_explicativos=[Hallazgo(afirmacion="real", impacto="positivo", fuentes=["S1"]),
                               Hallazgo(afirmacion="inventado", impacto="negativo", fuentes=["S99"])],
        dimensiones=[Dimension(nombre="clima", senal="desfavorable",
                               hallazgos=[Hallazgo(afirmacion="sin fuente", impacto="negativo", fuentes=[])])],
        preguntas_para_el_cliente=[], vacios_de_informacion=[])
    limpio, descartados = validar(inf, {"S1": DOCS[0]})
    assert [h.afirmacion for h in limpio.factores_explicativos] == ["real"]
    assert limpio.dimensiones[0].senal == "sin_evidencia"
    assert descartados == 2


def test_filtro_de_fuentes():
    assert clasificar("gestion.pe") == "medio"
    assert clasificar("www.gob.pe".removeprefix("www.")) == "oficial"
    assert clasificar("facebook.com") is None
    assert clasificar("blog-cualquiera.com") is None


def test_bcrp_periodos_y_resumen():
    assert _periodo("Set.2026") == "2026-09"
    s = {"datos": [{"periodo": f"2025-{m:02d}", "valor": float(m)} for m in range(1, 13)]
         + [{"periodo": "2026-01", "valor": 20.0}]}
    r = resumen(s)
    assert r["ultimo"]["valor"] == 20.0 and r["hace_12m"]["periodo"] == "2025-01" and r["max_12m"]["valor"] == 20.0
