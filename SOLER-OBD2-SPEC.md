# SOLER OBD2 AI SCANNER

## Escaner OBD-II Inteligente con Agente AI

**Version:** 1.0.0  
**Autor:** Allan Solis / Soler Systems  
**Fecha:** Abril 2026

---

## Que es

Un escaner OBD-II inteligente con agente AI integrado que:

- Se conecta a CUALQUIER vehiculo con puerto OBD-II (1996+ USA, 2001+ Europa)
- Lee, interpreta y diagnostica en tiempo real todos los sistemas del vehiculo
- Genera mapas ECU personalizados para optimizar rendimiento y eficiencia
- Aprende de cada escaneo y mejora automaticamente sus diagnosticos
- Evoluciona su base de conocimiento sin intervencion humana

---

## Instalacion

### Requisitos

- Python 3.11+
- Node.js 18+
- Adaptador ELM327 (USB/Bluetooth/WiFi) o modo simulacion

### Backend

```bash
cd backend
pip install -r requirements.txt
python main.py
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Modo Simulacion (sin vehiculo)

```bash
cd backend
python main.py --simulate
```

---

## Arquitectura

```
soler-obd2-ai-scanner/
├── backend/
│   ├── obd/            # Conexion OBD-II y lectura de sensores
│   ├── ai_agent/       # Agente AI con motor de reglas
│   ├── tuning/         # Generador de mapas ECU
│   ├── api/            # FastAPI + WebSocket server
│   ├── database/       # SQLAlchemy models + SQLite
│   └── emulator/       # Emulador ELM327 para testing
├── frontend/           # React + TypeScript dashboard
├── vendor/             # Repos open source integrados
├── data/               # Knowledge base, DTCs, vehicle profiles
└── docs/               # Documentacion
```

---

## Stack Tecnologico

| Capa | Tecnologia |
|------|-----------|
| Frontend | React 18, TypeScript, Tailwind CSS, Recharts, WebSocket |
| Backend | Python 3.11, FastAPI, python-OBD, python-can, udsoncan |
| AI Agent | Motor de reglas experto, analisis de correlacion, predictor |
| Database | SQLite (async), Redis (cache) |
| Tuning | NumPy para mapas ECU, perfiles parametricos |
| Hardware | ELM327 v1.5+, OBDLink, J2534 PassThru |

---

## Protocolos Soportados

- SAE J1850 PWM (Ford)
- SAE J1850 VPW (GM)
- ISO 9141-2 (Chrysler, Asia, Europa)
- ISO 14230 KWP2000 (Europa)
- ISO 15765-4 CAN 11bit/500k (moderno estandar)
- ISO 15765-4 CAN 29bit/500k
- SAE J1939 CAN (camiones pesados)

---

## Modulos

### 1. Conexion OBD-II
Auto-deteccion de adaptador, negociacion de protocolo, reconexion automatica.

### 2. Lectura de Sensores
150+ PIDs estandar, streaming en tiempo real a 10Hz, todos los modos OBD-II (01-0A).

### 3. Diagnostico DTC
3000+ codigos con descripcion en espanol, clasificacion por severidad, Freeze Frame.

### 4. Agente AI
200+ reglas de diagnostico experto, correlacion multi-sensor, prediccion de fallas, auto-mejora.

### 5. Mapeo ECU / Tuning
Mapas 3D de inyeccion, encendido, boost, VVT. 4 perfiles: Eco, Stage 1, Sport, Stage 2.

### 6. Dashboard
Gauges en tiempo real, heatmaps 3D, chat con agente AI, historial de escaneos.

---

## API Endpoints

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| POST | /api/connect | Conectar al vehiculo |
| POST | /api/disconnect | Desconectar |
| GET | /api/vehicle-info | Info del vehiculo (VIN) |
| GET | /api/sensors | Lectura actual de sensores |
| WS | /api/ws/sensors | Streaming en tiempo real |
| GET | /api/dtc | Leer codigos de falla |
| POST | /api/dtc/clear | Borrar DTCs |
| GET | /api/diagnosis | Diagnostico AI completo |
| GET | /api/health-score | Salud del vehiculo 0-100% |
| GET | /api/tuning/maps/{profile} | Obtener mapas ECU |
| POST | /api/ai/chat | Chat con agente AI |
| GET | /api/history | Historial de escaneos |

---

## Perfiles de Tuning

| Parametro | Eco | Stage 1 | Sport | Stage 2 |
|-----------|-----|---------|-------|---------|
| Inyeccion | -8% | +4% | +8% | +12% |
| Encendido | -1 grado | +2 grados | +4 grados | +6 grados |
| Boost | -15% | +10% | +18% | +30% |
| Rev Limit | -500 rpm | stock | +500 rpm | +1000 rpm |
| Resultado | +8-15% mpg | +5-12% HP | +10-20% HP | +18-35% HP |

---

## Repos Open Source Integrados

- [python-OBD](https://github.com/brendan-w/python-OBD) — Comunicacion OBD-II
- [pyobd](https://github.com/barracuda-fsh/pyobd) — Diagnostico visual
- [ELM327-emulator](https://github.com/Ircama/ELM327-emulator) — Emulador para testing
- [Atlas](https://github.com/MOTTechnologies/atlas) — Tuning ECU open source
- [LibreTune](https://github.com/RallyPat/LibreTune) — Tuning compatible TunerStudio
- [OBD2 PID Reference](https://github.com/evrenonur/obd2-elm327-pid-reference) — Referencia de PIDs

---

## Disclaimer

> La modificacion de la ECU puede invalidar la garantia del vehiculo. Un mapa ECU incorrecto puede causar dano permanente al motor. En muchos paises, modificar los sistemas de emisiones es ilegal para vehiculos de uso en via publica. Este software genera mapas como PUNTO DE PARTIDA para tuners profesionales. SIEMPRE deben ser verificados en dinamometro. El usuario asume toda responsabilidad.

---

## Licencia

MIT

**SOLER OBD2 AI SCANNER** — Soler Systems 2026
