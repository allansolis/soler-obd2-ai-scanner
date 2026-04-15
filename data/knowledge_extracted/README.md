# knowledge_extracted/

Artefactos producidos por `backend/knowledge_hub/pdf_analyzer.py`.

## Ejecutar

```bash
# Requisito: pip install pymupdf
cd /c/Users/andre/OneDrive/Desktop/soler-obd2-ai-scanner

# Prueba rapida (100 PDFs mas ricos, 4 workers)
python backend/knowledge_hub/pdf_analyzer.py --limit 100 --workers 4

# Todo el corpus (1464 PDFs, multiprocess)
python backend/knowledge_hub/pdf_analyzer.py --workers 6 --max-pages 50

# Solo ciertas carpetas
python backend/knowledge_hub/pdf_analyzer.py --only obd-diesel,datos-tecnicos
```

## Archivos generados

- `pdf_analysis.json` - lista de PDFs analizados + stats globales
- `dtc_sources.json` - mapa inverso DTC -> PDFs que lo mencionan
- `_cache/*.json` - cache por hash de archivo (reanalizar sin re-leer)

## Consumidores

- `backend/knowledge_hub/knowledge_graph.py` - grafo transitivo
- `backend/knowledge_hub/enhanced_profiles.py` - perfiles enriquecidos
- `backend/knowledge_hub/expert_advisor.py` - metodos `get_evidence()`,
  `context_for_vehicle()`, `recommend_tools_for_dtc_with_evidence()`
- `backend/api/routes_expert.py` - endpoints `/api/expert/evidence/*`,
  `/api/expert/context`
- `frontend/src/pages/ExpertMode.tsx` - tab Evidencia en cada recomendacion
