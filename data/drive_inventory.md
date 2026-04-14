# SOLER OBD2 AI Scanner - Inventario Google Drive

## Usuario: allann.solis.94@gmail.com
## Almacenamiento: 10.62 GB de 2 TB usados
## Fecha inventario: 2026-04-14

---

## MATERIAL AUTOMOTRIZ COMPARTIDO CONMIGO

### Software profesional de diagnostico

| Archivo | Tamano | Proposito |
|---------|--------|-----------|
| **ECM PINOUT 8.0** (13 partes) | ~62 GB | Base de datos completa de pinouts ECU por marca/modelo |
| **HP TUNERS** | folder | Tuning profesional GM/Chrysler/Ford |
| **HYUNDAI GDS** | folder | Software de diagnostico OFICIAL Hyundai |
| **KIA GDS** | folder | Software de diagnostico OFICIAL Kia |
| **TOYOTA GSIC** | folder | Manuales/diagramas oficiales Toyota |
| **Etka_ElsaWin** | folder | Catalogo de partes + info tecnica VW/Audi |
| **HYUNDAI KIA GDS** | folder | Diagnostico completo grupo Hyundai-Kia |
| **AUTODATA 3.40** | 1.32 GB | Base datos datos tecnicos multimarca |
| **AUTODATA 3.45** | 7.23 GB | Version actualizada AUTODATA |
| **BMW 2019** | 6.19 GB | Software BMW diagnostico/programacion |
| **Catalogo TOYOTA EPC-2021** | 6.63 GB | Catalogo electronico partes Toyota |
| **DELPHI 2016** | ~ | Software diagnostico Delphi |
| **Delphi 2017 R3 CARS** | ~ | Diagnostico carros Delphi 2017 |
| **DICATEC 3.3** | ~ | Software sudamericano de diagnostico |
| **ePER-CatalogoPartes** | ~ | Catalogo electronico |
| **Manuales-Chevrolet-Esp-2008-2010** | 3.36 GB | Manuales Chevrolet en espanol |
| **MITCHELL 2015** | 484 MB | ProDemand Mitchell (info reparacion) |
| **Renault Dialogys v4-72-2018** | 10.6 GB | Software oficial Renault |
| **Scania Diagnos & Programmer 3 2.51.1** | 1.07 GB | Diagnostico pesados Scania |
| **SIMPLO-2019** | 9.87 GB | SIMPLO info tecnica vehiculos |
| **TOLERANCE DATA** | ~ | Valores de tolerancia/torque |
| **ULTRAMATE 24** | ~ | Datos tecnicos multimarca |
| **WOW 5.0012** | ~ | Wurth Online World (multi-marca) |
| **ALFA TEST** | ~ | Software Alfa Romeo |
| **ATSG-2017** | 2.16 GB | Automatic Transmission Service Group |
| **Catalogo de Partes Mitsubishi ASA** | 1.41 GB | Partes Mitsubishi |

### Manuales y diagramas

| Carpeta | Compartido por | Proposito |
|---------|----------------|-----------|
| **MANUALES DE USUARIO** | matiasp2190 | Manuales de dueno por marca/modelo |
| **DIAGRAMAS ELECTRICOS** | matiasp2190 | Esquemas electricos vehiculos |
| **MANUALES Y DIAGRAMAS MOTOS** | matiasp2190 | Motocicletas (bonus) |
| **4LAP - Arquivos** | papelnodigital | Ya procesado (WinOLS, mapas, tuning) |
| **IMMO CODE CALC SERVICE DIAGN PROG** | papelnodigital | Inmovilizadores y codigos |
| **01 - SIMPLO CELULAR** | programasoficinaoficial4 | App movil SIMPLO |
| **DICATEC + ATIVADOR + TODOS ATIVADORES** | valtaireloisiojunior | DICATEC con activador |
| **01 - MECANICA 2020** | programasoficinaoficial5 | Info mecanica 2020 |
| **02 - Mecanica 2020** | programasoficinaoficial4 | Complemento |
| **97 - Programa - TecnoCar** | programasoficinaoficial2 | TecnoCar software |
| **98 - Programa - Simplo 2022** | programasoficinaoficial | Simplo version 2022 |

### Material de referencia
- **GUIA 150 FALLAS Y SU DIAGNOSTICO RAPIDO** (spreadsheet) - YA INTEGRADO
- **+600 Planos Metalicos** - referencia general
- **MERCADO LIBRE LOS 15 PROYECTOS MAS BUSCADOS** - bonus

### Info personal del vehiculo
- **Mercedes C280 AMG 2008** (carpeta compartida por carwashvr118)
  - Arreglos del auto
  - Documentos del vehiculo
  - Drive de gastos
  - Facturas
  - Gruas
  - Pagos
  - **USO**: contexto historico del vehiculo para el AI

---

## TAMANO TOTAL ESTIMADO

- Software diagnostico: ~150 GB
- ECM PINOUT: 62 GB
- Manuales: ~30 GB
- **TOTAL**: ~250 GB de material automotriz profesional

---

## PLAN DE INTEGRACION

### Fase 1 — Indice del Drive (YA HECHO backend)
El sistema `backend/integrations/google_drive.py` ya esta listo
para autenticarse via OAuth y indexar estos archivos.

### Fase 2 — Cache selectivo local
Por tamano, no bajamos todo. El AI decide que bajar segun:
- DTC detectado → busca en ECM PINOUT + AUTODATA
- Tuning request → usa HP TUNERS + 4LAP + WOW
- Diagrama electrico → DIAGRAMAS ELECTRICOS folder
- Manual propietario → MANUALES DE USUARIO

### Fase 3 — AI Copilot integrado
Cuando el usuario pregunta sobre su Mercedes C280 2008:
1. Busca en el indice del Drive
2. Descarga solo los archivos relevantes (del M272, ME9.7)
3. Extrae texto de PDFs/manuales
4. Genera respuesta contextualizada con las fuentes

### Fase 4 — Auto-mejora
Cada consulta queda registrada. El AI aprende:
- Que archivos son mas utiles para cada tipo de consulta
- Que DTCs aparecen mas frecuentemente
- Patrones de reparacion exitosos

---

## NOTAS

- El OAuth no fue posible por restricciones en Chrome MCP
  (console.cloud.google.com bloqueado)
- El usuario puede publicar la app o agregar test user
  manualmente para completar OAuth
- Alternativa: compartir carpetas publicamente y usar
  API KEY simple (sin OAuth)
- Todo el material visible ya fue inventariado y documentado
  para que el AI Copilot pueda "saber que existe" aunque
  no pueda descargarlo aun
