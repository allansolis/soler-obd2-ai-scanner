# Modo Experto - SOLER OBD2 AI Scanner

## Que es

El **Modo Experto** es el sistema asesor de SOLER que conoce a fondo cada
herramienta automotriz del inventario (HP Tuners, BMW ISTA, Hyundai/Kia GDS,
ECM Titanium, KESS V2/V3, KTAG, WinOLS, Autodata, Mitchell ProDemand,
WOW Wurth, Toyota GSIC, etc.) y recomienda cual usar para cada escenario
concreto.

Funciona en tres modos:

1. **Asesor**: describes el problema (DTC, tuning, programacion) y el sistema
   recomienda las mejores herramientas disponibles, con score, razon y
   workflow resumido.
2. **Comparador**: seleccionas 2-5 herramientas y obtienes una matriz lado a
   lado (categoria, marcas, hardware, fortalezas, limitaciones).
3. **Biblioteca**: explora el perfil completo de cualquier herramienta
   (descripcion, protocolos, casos de uso, alternativas, conocidos issues).

## Arquitectura

```
backend/knowledge_hub/expert_profiles.json   <- conocimiento estructurado
backend/knowledge_hub/expert_advisor.py      <- motor de razonamiento
backend/api/routes_expert.py                 <- API REST
frontend/src/pages/ExpertMode.tsx            <- UI Espanol
```

Los perfiles son indexados tambien en la SQLite del KnowledgeHub
(`SoftwareTool` + `Resource`) durante `compile_all()`, asi el AI Copilot
y la busqueda global tambien los conocen.

## Endpoints

| Metodo | Ruta | Descripcion |
|---|---|---|
| GET  | `/api/expert/tools` | Lista todos los perfiles |
| GET  | `/api/expert/tool/{id}` | Perfil deep de una herramienta |
| POST | `/api/expert/advise` | Recomienda herramientas para un escenario |
| GET  | `/api/expert/workflow/{tool}/{task}` | Workflow paso a paso |
| POST | `/api/expert/compare` | Compara N herramientas |
| POST | `/api/expert/reload` | Recarga el JSON desde disco |

### POST /api/expert/advise

```json
{
  "scenario": "dtc",            // "dtc" | "tuning" | "programming"
  "dtc": "P0420",
  "make": "Hyundai",
  "model": "Tucson",
  "year": 2018,
  "goal": "stage1",             // solo tuning
  "task": "key_programming"     // solo programming
}
```

Respuesta:

```json
{
  "scenario": "dtc",
  "recommendations": [
    {
      "tool_id": "hyundai_kia_gds",
      "name": "Hyundai/Kia GDS",
      "score": 95,
      "confidence": "alta",
      "reason_es": "Scanner OEM oficial...",
      "workflow_summary": "Conectar VCI II...",
      "alternatives": ["G-Scan", "Launch X431"]
    }
  ]
}
```

## Como agregar una herramienta

1. Abrir `backend/knowledge_hub/expert_profiles.json`
2. Agregar entrada bajo `tools` con la siguiente estructura:

```json
"tool_id": {
  "id": "tool_id",
  "name": "Nombre",
  "category": "tuning_software | oem_diagnostic | ...",
  "publisher": "Empresa",
  "description_es": "Descripcion completa en espanol...",
  "supports": {
    "brands": ["Marca1", "Marca2"],
    "protocols": ["OBD-II", "CAN", ...],
    "functions": ["lectura DTC", "tuning", ...]
  },
  "hardware_required": ["KESS V3", "..."],
  "use_cases": [...],
  "typical_workflow": "1. Paso uno\n2. Paso dos",
  "strengths": [...],
  "limitations": [...],
  "license": "comercial",
  "learning_curve": "facil | intermedio | avanzado | experto",
  "alternatives": [...],
  "official_url": "https://..."
}
```

3. Llamar `POST /api/expert/reload` o reiniciar el backend.
4. Re-compilar el KnowledgeHub para indexar (`POST /api/hub/compile`).

## Razonamiento del Advisor

El `ExpertAdvisor` razona segun heuristicas por escenario:

- **DTC**: prioriza el SW OEM de la marca, agrega Mitchell/Autodata como
  base de causa raiz, y sugiere ECM PINOUT cuando el codigo aparenta ser
  de circuito (corto/abierto).
- **Tuning**: HP Tuners para US domestic (GM/Ford/Chrysler), combo
  KESS+ECM Titanium o KESS+WinOLS para europeos y diesel; KTAG si se
  requiere bench/boot.
- **Programming**: SW OEM cuando aplica + J2534 generico + IMMO Code
  Calculator para llaves perdidas.

Cada recomendacion tiene `score` (0-100), `confidence` y razon textual
en espanol lista para mostrar al tecnico.

## Notas de seguridad

Cada workflow incluye `safety_notes`. Las criticas son:

- Bateria estable >12.5V durante read/write de ECU.
- Backup obligatorio del archivo stock antes de escribir.
- No interrumpir comunicacion durante flash (puede ladrillar la ECU).
- Validar tunes con datalog antes de entregar al cliente.
