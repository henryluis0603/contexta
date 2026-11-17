# Entrega y presentación

## 1. Publicar en Streamlit Community Cloud (≈ 10 minutos)

1. Crea una **clave nueva** de OpenAI en https://platform.openai.com/api-keys (la anterior expiró) y fija un tope de gasto en *Settings → Limits* (p. ej. US$ 10/mes).
2. Entra a https://share.streamlit.io con tu cuenta de GitHub → **Create app** → *Deploy a public app from GitHub*.
3. Repositorio `henryluis0603/contexta`, rama `main`, archivo `app/streamlit_app.py`.
4. En **Advanced settings**:
   - Python 3.12.
   - En **Secrets** pega (con tu clave, entre comillas):
     ```toml
     OPENAI_API_KEY = "sk-..."
     ```
5. **Deploy.** La primera vez tarda unos minutos porque instala LaTeX (`packages.txt`).
6. Prueba con Cementos Pacasmayo: que aparezca la ficha, las 6 dimensiones y que descargue el PDF.
7. Copia la URL en el README (tabla del inicio y sección 6) y pásala a 2 personas para que la prueben.

La clave nunca va en el repo: en Cloud vive en *Secrets*; en local, en `.env` (ignorado por git).

## 2. Pitch de 3 minutos

**0:00–0:30 · El problema.**
"Trabajo en auditoría interna de riesgos en banca. La SBS nos pide revisar si la clasificación de un deudor es consistente con su situación. Desde la Res. SBS 2368-2023, la categoría CPP considera explícitamente la sensibilidad del flujo de caja a 12 meses frente al entorno económico, comercial, regulatorio y político. Pero el entorno hoy se revisa a mano en Google, o no se revisa." "En mi equipo revisamos 20 empresas al mes en una ventana de 3 días, y solo buscar el contexto toma 15 a 20 minutos por empresa."

**0:30–0:50 · Quién lo sufre.**
"Los auditores internos de riesgo de crédito. En una reunión de mi área se cuestionó justamente que no estábamos considerando el contexto socioeconómico, y que buscar fuentes toma tiempo. Mi jefa, que me pidió anclarlo en la 2368-2023, quiere llevarlo al equipo que desarrolla agentes en el banco."

**0:50–2:10 · Demo en vivo.**
1. Escribo "Cementos Pacasmayo" y presiono Enter: detecta sola el sector y subsector.
2. Genero el informe: ficha con ventas, grupo económico y tipo de crédito referencial según la 2368-2023.
3. Las 6 dimensiones con su señal; abro una y muestro que cada afirmación tiene su fuente enlazada.
4. Señales y alertas (ratings de Moody's Local y Apoyo con sus fundamentos, OPA de Holcim, multas de OEFA y SUNAFIL) y el grupo económico (riesgo único).
5. Insumos para la clasificación, agrupados por los criterios de la norma, y los puntos de verificación.
6. Descargo el PDF: "esto se adjunta al papel de trabajo".

**2:10–2:40 · Por qué funciona.**
"La regla central es: sin fuente, no hay afirmación. Toda afirmación sin una cita válida se elimina antes de mostrarse. Un auditor no puede sustentar con 'la IA dice que'."

**2:40–3:00 · Negocio y cierre.**
"Cada informe cuesta unos 8 centavos de dólar. El equipo de auditoría pagaría S/ 70 al mes: S/ 3.50 por empresa, con un margen del 91 %." "Auditrail: el entorno del deudor, con evidencia auditable."

**Plan B:** si falla internet o la API, pasa el video de respaldo o abre un PDF ya generado.

## 3. Video de respaldo (60–90 s)

Graba la pantalla con la app publicada (en Mac: Cmd + Shift + 5), sin cortes largos:

| Tiempo | Pantalla | Narración |
|---|---|---|
| 0–10 s | Portada de la app | "Auditrail ayuda a los auditores internos a revisar el entorno de un deudor, como pide la SBS." |
| 10–25 s | Escribes la empresa, se detecta el sector | "Escribo la empresa y detecta el sector y subsector." |
| 25–50 s | Ficha, dimensiones y una dimensión abierta | "Ficha con ventas y tipo de crédito, y el entorno en 6 dimensiones; cada afirmación tiene su fuente." |
| 50–70 s | Insumos SBS y puntos de verificación | "Insumos para la clasificación según la 11356 y la 2368-2023, y qué verificar en el expediente." |
| 70–85 s | Descarga y PDF abierto | "Y el informe en PDF, listo para el papel de trabajo." |

Súbelo a YouTube como **no listado** y pega el link en el README.

## 4. Texto para el issue #205

```
**Auditrail** · Henry Llupton
Análisis del entorno del deudor, con fuentes citadas, para auditores internos de riesgo de crédito (Res. SBS 11356-2008 y 2368-2023).

- Demo: https://auditrail.streamlit.app
- Repo: https://github.com/henryluis0603/contexta
- Video: https://youtu.be/UFqE79TUiv8
```

## 5. Checklist final (lunes 16)

- [ ] URL, video, foto y 3 capturas en el README.
- [ ] Sección 3 con los datos de las entrevistas y notas en `docs/research/`.
- [ ] Precios de los planes definidos en la sección 7.
- [ ] Sin secretos: `git log -p | grep -n "sk-"` no debe devolver nada.
- [ ] Comentario en el issue #205 antes de las 11:59 pm.
- [ ] Ensayar el pitch con cronómetro.
