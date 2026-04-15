# SOLER OBD2 AI Scanner

Escaner OBD2 con copiloto AI, diagnostico inteligente, base de conocimiento y tuning seguro.

## Quickstart

### Backend

```bash
cd soler-obd2-ai-scanner
cp .env.example .env
# edita .env con ANTHROPIC_API_KEY y API_KEY
pip install -r requirements.txt
uvicorn backend.api.server:app --reload --port 8000
```

Visita http://localhost:8000/docs para la documentacion.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Abre http://localhost:5173.

## Variables de entorno

| Variable | Proposito |
|---|---|
| `ANTHROPIC_API_KEY` | Habilita Claude real en `/api/ai/chat`. Si esta vacio, usa fallback por palabras clave. |
| `API_KEY` | Si esta definida, exige header `X-API-Key` en `/api/launcher/*`. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth Google Drive. |
| `DATABASE_URL` | Conexion DB (por defecto SQLite). |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

## Endpoints clave

- `GET /health` - health check + estado de servicios
- `POST /api/ai/chat` - copiloto AI (Claude + fallback)
- `POST /api/ai/repair-guide` - guia paso a paso DTC + evidencia
- `POST /api/ai/scan-full` - escaneo completo
- `GET /api/launcher/drives` - drives montados (requiere API key si configurada)

## Arquitectura

- `backend/api/` - FastAPI
- `backend/ai_agent/` - copiloto, Claude client, rules engine
- `backend/knowledge_hub/` - SQLite con DTCs, procedimientos, recursos
- `backend/obd/` - drivers OBD-II
- `frontend/` - React + Vite + Tailwind

## Seguridad

- CORS restringido a localhost (configurable en `backend/config.py`)
- Path traversal bloqueado en launcher (usa `Path.is_relative_to`)
- API key opcional para endpoints del launcher
