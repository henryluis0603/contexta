"""Pruebas sin internet ni API key: fragmentación, recuperación y validación de citas."""
from ai.rag import (AlertaExterna, AlertaSBS, DatoFicha, GrupoEconomico, Vinculada, Dimension, EmbedderTFIDF, Hallazgo, Indice, Informe, armar_evidencia, fragmentar, recuperar,
                    validar)
from backend.models import Documento
from backend.sources.bcrp import _periodo, resumen
from backend.sources.noticias import clasificar, es_de_otro_pais

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
        resumen_ejecutivo="x",
        ficha_empresa=[DatoFicha(campo="ruc", valor="20601356661", fuentes=["S1"]),
                       DatoFicha(campo="ubicacion", valor="inventada", fuentes=["S50"])],
        factores_explicativos=[Hallazgo(afirmacion="real", implicancia="", impacto="positivo", fuentes=["S1"]),
                               Hallazgo(afirmacion="inventado", implicancia="", impacto="negativo", fuentes=["S99"])],
        dimensiones=[Dimension(nombre="clima", senal="desfavorable", sintesis="",
                               hallazgos=[Hallazgo(afirmacion="sin fuente", implicancia="", impacto="negativo",
                                                   fuentes=[])])],
        insumos_clasificacion_sbs=[
            AlertaSBS(afirmacion="con fuente", implicancia="", impacto="negativo", fuentes=["S1"],
                      criterio="entorno_comercial"),
            AlertaSBS(afirmacion="sin fuente", implicancia="", impacto="negativo", fuentes=["S7"],
                      criterio="riesgo_cambiario")],
        senales_y_alertas=[], grupo_economico=GrupoEconomico(pertenece="no_hallado", nombre_del_grupo="",
                                                            sintesis="", vinculadas=[], hallazgos=[]),
        puntos_de_verificacion=[], vacios_de_informacion=[])
    limpio, descartados = validar(inf, {"S1": DOCS[0]})
    assert [h.afirmacion for h in limpio.factores_explicativos] == ["real"]
    assert [h.criterio for h in limpio.insumos_clasificacion_sbs] == ["entorno_comercial"]
    assert limpio.dimensiones[0].senal == "sin_evidencia"
    assert [d.campo for d in limpio.ficha_empresa] == ["ruc"]
    assert descartados == 4


def test_validar_grupo_y_alertas():
    """Las alertas y las vinculadas sin fuente válida se eliminan; un grupo sin evidencia queda 'no_hallado'."""
    def alerta(fuentes):
        return AlertaExterna(afirmacion="multa OEFA", implicancia="", impacto="negativo", fuentes=fuentes,
                             categoria="sancion_administrativa", fecha_del_hecho="2025", relevancia="alta")
    inf = Informe(
        resumen_ejecutivo="x", ficha_empresa=[], factores_explicativos=[], dimensiones=[],
        insumos_clasificacion_sbs=[], puntos_de_verificacion=[], vacios_de_informacion=[],
        senales_y_alertas=[alerta(["S1"]), alerta(["S9"]),
                           AlertaExterna(afirmacion="No se encontraron sanciones de SUNAFIL.", implicancia="",
                                         impacto="neutral", fuentes=["S1"], categoria="sancion_administrativa",
                                         fecha_del_hecho="s/f", relevancia="baja")],
        grupo_economico=GrupoEconomico(pertenece="si", nombre_del_grupo="Grupo X", sintesis="s", hallazgos=[],
                                       vinculadas=[Vinculada(empresa="X S.A.", relacion="matriz", situacion="s",
                                                             impacto="neutral", fuentes=["S8"])]))
    limpio, descartados = validar(inf, {"S1": DOCS[0]})
    assert len(limpio.senales_y_alertas) == 1
    assert limpio.grupo_economico.pertenece == "no_hallado" and limpio.grupo_economico.nombre_del_grupo == ""
    assert descartados == 2


def test_filtro_de_fuentes():
    assert clasificar("gestion.pe") == "medio"
    assert clasificar("www.gob.pe".removeprefix("www.")) == "oficial"
    assert clasificar("facebook.com") is None
    assert clasificar("blog-cualquiera.com") is None


def test_descarta_secciones_de_otros_paises():
    assert es_de_otro_pais("https://www.infobae.com/colombia/2026/08/10/reforma-tributaria/")
    assert not es_de_otro_pais("https://www.infobae.com/peru/2026/10/25/el-nino/")
    assert not es_de_otro_pais("https://gestion.pe/economia/el-nino-industria/")


def test_bcrp_periodos_y_resumen():
    assert _periodo("Set.2026") == "2026-09"
    s = {"datos": [{"periodo": f"2025-{m:02d}", "valor": float(m)} for m in range(1, 13)]
         + [{"periodo": "2026-01", "valor": 20.0}]}
    r = resumen(s)
    assert r["ultimo"]["valor"] == 20.0 and r["hace_12m"]["periodo"] == "2025-01" and r["max_12m"]["valor"] == 20.0



def test_catalogo_de_subsectores_y_lista_demo():
    import pandas as pd
    from backend.sources.bcrp import SECTORES, SUBSECTORES
    assert set(SUBSECTORES) == set(SECTORES)
    assert all(subs and all(v["palabras"] for v in subs.values()) for subs in SUBSECTORES.values())
    demo = pd.read_csv("data/empresas_demo.csv")
    for _, f in demo.iterrows():
        assert f.subsector in SUBSECTORES[f.sector], f.empresa


def test_detector_sin_api_key_no_inventa(monkeypatch):
    from ai.detectar_sector import OPCIONES, detectar_sector
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert detectar_sector("Alicorp") is None
    assert "Manufactura › Consumo masivo (alimentos, bebidas, higiene)" in OPCIONES


def test_web_sin_clave_no_rompe_nada(monkeypatch):
    from backend.sources.web import buscar_web, tipo_fuente
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert buscar_web("Sycpha S.A.C.") == []
    assert tipo_fuente("https://www.gob.pe/institucion/produce/normas") == "oficial"
    assert tipo_fuente("https://gestion.pe/x") == "medio"
    assert tipo_fuente("https://www.universidadperu.com/empresas/x.php") == "directorio"


def test_parrafos_sin_enlace_se_asignan_a_la_cita_siguiente():
    from backend.sources.web import asignar_parrafos
    u1, u2 = "https://elruc.pe/x?utm_source=openai", "https://www.gob.pe/y?utm_source=openai"
    texto = (f"- **RUC**: 20118800371\n- **Estado**: Activo y habido\n- ([elruc.pe]({u1}))\n"
             f"- **Habilitación**: licencia de planta ([gob.pe]({u2}))\nNota final sin cita")
    pags = asignar_parrafos(texto, {u1: ("https://elruc.pe/x", "elruc"), u2: ("https://www.gob.pe/y", "gob")})
    assert pags["https://elruc.pe/x"]["parrafos"] == ["- **RUC**: 20118800371", "- **Estado**: Activo y habido"]
    assert pags["https://www.gob.pe/y"]["parrafos"][0].startswith("- **Habilitación**")
    assert "Nota final sin cita" in pags["https://www.gob.pe/y"]["parrafos"]
