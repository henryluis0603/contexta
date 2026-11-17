# Arquitectura de Auditrail

El auditor escribe el nombre de la empresa; Auditrail detecta su sector, reúne evidencia (búsqueda web, noticias y series del BCRP), genera el informe con un LLM con salida estructurada y elimina toda afirmación sin cita válida antes de mostrarla en la app o en el PDF.

```mermaid
flowchart LR
    U[Auditor] -->|nombre de la empresa| DET[ai/detectar_sector.py<br/>sector y subsector]
    U -.->|desde Claude| MCP[Servidor MCP mcp_server/]
    DET --> APP[Streamlit app/]
    APP --> REC[backend/recolector.py]
    MCP --> REC
    REC --> W[web.py<br/>búsqueda web → ficha: RUC, ventas, grupo]
    REC --> N[noticias.py<br/>Google News RSS → URL original → texto]
    REC --> B[bcrp.py<br/>API de series del BCRP, sector y subsector]
    N --> F{Filtro de fuentes<br/>oficiales y medios, solo Perú}
    W --> RAG
    F --> RAG[ai/rag.py<br/>fragmentar → embeddings → cuota x 6 dimensiones]
    B --> RAG
    RAG --> LLM[OpenAI · salida estructurada<br/>marco SBS 11356-2008 y 2368-2023]
    LLM --> V[Validación de citas]
    V --> APP
    APP --> PDF[backend/reporte_pdf.py<br/>informe PDF]
```
