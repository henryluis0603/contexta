"""Estructuras de datos compartidas por la ingesta, el RAG y la app."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

# Las seis dimensiones del contexto que el analista suele no revisar.
DIMENSIONES = {
    "empresa": "Noticias sobre la propia empresa: inversiones, adquisiciones, resultados, financiamiento, litigios, reputación",
    "sector": "Situación y desempeño del sector económico: demanda, precios, producción, competencia",
    "macro": "Contexto macroeconómico peruano: crecimiento, inflación, tasa de referencia, tipo de cambio",
    "clima": "Factores climáticos y naturales: Fenómeno El Niño, lluvias, sequías, huaicos, temperatura del mar",
    "regulatorio": "Cambios regulatorios, tributarios o de política pública que afectan al sector o a la empresa",
    "social": "Conflictos sociales, paros, bloqueos, inseguridad, extorsión o tensión política que afectan la operación",
}

# Base normativa: Reglamento para la Evaluación y Clasificación del Deudor y la Exigencia de Provisiones
# (Res. SBS N.° 11356-2008), modificado por la Res. SBS N.° 2368-2023 (14/07/2023). Texto oficial verificado en
# https://intranet2.sbs.gob.pe/dv_int_cn/2290/v2.0/Adjuntos/2368-2023.pdf
# Contexta cubre solo el contexto EXTERNO; no asigna la categoría (Normal, CPP, Deficiente, Dudoso, Pérdida),
# que es responsabilidad de la entidad y la revisa el auditor.
NORMA_CPP = ("Res. SBS N.° 2368-2023, que modifica el numeral 2.2 del Capítulo II del Reglamento (Res. SBS N.° "
             "11356-2008), categoría Con Problemas Potenciales de deudores no minoristas, literal a): «El flujo de "
             "caja podría, en los próximos doce (12) meses, debilitarse para afrontar los pagos, dado que es "
             "sumamente sensible a modificaciones de variables relevantes como entorno económico, comercial, "
             "regulatorio, político, entre otros». Vigente desde el 01/10/2024.")
NORMA_MYPE = ("Para pequeña empresa y microempresa, el numeral 5.1 modificado por la Res. SBS N.° 2368-2023 señala: "
              "«Adicionalmente, se puede considerar información sobre el entorno social y económico del deudor».")
# Tipos de crédito por ventas o ingresos anuales declarados a la autoridad tributaria (Res. SBS N.° 2368-2023,
# numerales 4.1 a 4.5, vigentes desde el 01/10/2024). La tipificación oficial la hace la entidad.
UMBRALES_TIPO = ("corporativo: ventas > S/ 200 millones en los 2 últimos periodos; gran empresa: > S/ 20 millones "
                 "en los 2 últimos periodos; mediana empresa: > S/ 5 millones en el último periodo; pequeña o "
                 "microempresa: ≤ S/ 5 millones (se distinguen por el endeudamiento en el sistema, mayor o no a "
                 "S/ 20 mil). Si la empresa pertenece a un grupo económico donde otra empresa supera el umbral, "
                 "toma el tipo de esa empresa.")

# Variables del entorno que nombra el literal a) del numeral 2.2 (CPP), más el riesgo cambiario.
CRITERIOS_SBS = {
    "entorno_economico": "Entorno económico en que opera el deudor: crecimiento, inflación, tasas, demanda agregada",
    "riesgo_cambiario": "Capacidad de pago ante variaciones del tipo de cambio (deuda o ingresos en moneda extranjera)",
    "entorno_comercial": "Entorno comercial y sectorial: demanda, precios, competencia, insumos, clima que afecta la operación",
    "entorno_politico_regulatorio": "Entorno político, regulatorio o tributario, y conflictos sociales que afectan la operación",
}

# Nombres para mostrar (app y PDF).
NOMBRE_DIM = {"empresa": "Empresa", "sector": "Sector", "macro": "Macroeconomía", "clima": "Clima",
              "regulatorio": "Regulatorio", "social": "Social y político"}
NOMBRE_CRIT = {"entorno_economico": "Entorno económico", "riesgo_cambiario": "Riesgo cambiario",
               "entorno_comercial": "Entorno comercial", "entorno_politico_regulatorio": "Entorno político y regulatorio"}
NOMBRE_FICHA = {"razon_social": "Razón social", "nombre_comercial": "Nombre comercial", "ruc": "RUC",
                "actividad_principal": "Actividad principal", "estado_y_condicion": "Estado y condición (SUNAT)",
                "inicio_de_actividades": "Inicio de actividades", "ubicacion": "Ubicación",
                "escala_u_operaciones": "Escala u operaciones", "habilitaciones_y_permisos": "Habilitaciones y permisos",
                "ventas_o_ingresos_anuales": "Ventas o ingresos anuales", "grupo_economico": "Grupo económico",
                "tipo_de_credito_referencial": "Tipo de crédito (referencial, Res. SBS 2368-2023)"}
NOMBRE_SENAL = {"favorable": "Favorable", "neutral": "Neutral", "desfavorable": "Desfavorable",
                "sin_evidencia": "Sin fuentes"}


@dataclass
class Documento:
    """Una pieza de evidencia citable: una noticia o una serie del BCRP."""

    titulo: str
    fuente: str          # medio o institución (Gestión, BCRP, Andina...)
    url: str
    fecha: str           # ISO yyyy-mm-dd
    dimension: str       # una de DIMENSIONES
    texto: str
    tipo: str = "noticia"          # "noticia" | "serie_bcrp"
    verificada: bool = False       # fuente oficial o medio reconocido
    id: str = field(default="")

    def __post_init__(self):
        if not self.id:
            self.id = hashlib.sha1(self.url.encode()).hexdigest()[:10]

    def to_dict(self) -> dict:
        return asdict(self)
