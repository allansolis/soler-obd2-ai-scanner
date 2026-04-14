# Guia de Configuracion - Google Drive Knowledge Base

Esta guia te lleva paso a paso para conectar tu Google Drive (2 TB) a
SOLER OBD2 AI Scanner y convertirlo en la base de conocimiento del
AI Copilot.

Tiempo estimado: 10 minutos.

---

## Paso 1 - Crear un proyecto en Google Cloud Console

1. Abre: https://console.cloud.google.com/
2. Inicia sesion con la misma cuenta Google que usa tu Drive de 2 TB.
3. En la barra superior haz clic en el selector de proyectos
   ("Select a project") y luego en "NEW PROJECT".
4. Nombre: `SOLER OBD2 Scanner` (o el que prefieras).
5. Haz clic en "CREATE".
6. Espera 10-20 segundos a que el proyecto este listo y seleccionalo.

---

## Paso 2 - Habilitar la Google Drive API

1. En el menu lateral: `APIs & Services` -> `Library`.
2. Busca "Google Drive API".
3. Haz clic en el resultado -> boton "ENABLE".

---

## Paso 3 - Configurar la pantalla de consentimiento OAuth

1. Menu lateral: `APIs & Services` -> `OAuth consent screen`.
2. User type: selecciona `External` -> `CREATE`.
3. Rellena los campos obligatorios:
   - App name: `SOLER OBD2 Scanner`
   - User support email: tu correo
   - Developer contact information: tu correo
4. Haz clic en `SAVE AND CONTINUE` en las siguientes pantallas.
5. En "Scopes" puedes dejar todo por defecto.
6. En "Test users" haz clic en `ADD USERS` y agrega tu propia cuenta
   Google. Guarda.
7. Vuelve al dashboard.

> Nota: No necesitas publicar la app ni pasar verificacion. Al estar
> en modo "Testing", solo los usuarios de prueba (tu) pueden usarla,
> que es exactamente lo que queremos.

---

## Paso 4 - Crear credenciales OAuth 2.0 (Desktop App)

1. Menu lateral: `APIs & Services` -> `Credentials`.
2. `+ CREATE CREDENTIALS` -> `OAuth client ID`.
3. Application type: `Desktop app`.
4. Name: `SOLER Desktop Client`.
5. `CREATE`.
6. Se abre un dialogo con un boton `DOWNLOAD JSON`. Descarga el archivo.

---

## Paso 5 - Instalar las credenciales en SOLER

1. Renombra el archivo descargado a `google_credentials.json`.
2. Muevelo a:
   ```
   soler-obd2-ai-scanner/config/google_credentials.json
   ```
   (crea la carpeta `config/` si no existe).

Estructura final esperada:

```
soler-obd2-ai-scanner/
  config/
    google_credentials.json    <- acabas de crear este
    google_token.json          <- se crea automaticamente tras autenticar
  data/
    google_drive_index.db      <- indice SQLite, se crea solo
```

---

## Paso 6 - Instalar dependencias de Python

```bash
cd soler-obd2-ai-scanner
pip install -r backend/requirements.txt
```

---

## Paso 7 - Autenticarte desde la app

1. Arranca el backend:
   ```bash
   python -m uvicorn backend.api.server:app --reload
   ```
2. Abre el frontend y navega a `Drive` en el menu lateral.
3. Haz clic en `Conectar Google Drive`.
4. Se abre tu navegador en `localhost:8080` con la pantalla de consent.
5. Elige tu cuenta, aceptar permisos (solo lectura).
6. Cuando veas "The authentication flow has completed" puedes cerrar
   esa pestaña. El token queda guardado en `config/google_token.json`.

---

## Paso 8 - Indexar tu Drive

1. En la pagina Drive del scanner haz clic en `Indexar ahora`.
2. La barra de progreso muestra el avance en tiempo real via WebSocket.
3. Para un Drive de 2 TB espera entre 30 minutos y varias horas, segun:
   - Cantidad de archivos
   - Porcentaje de PDFs (se extrae texto preview de los mas relevantes)
   - Cuota de la API de Google Drive (se respetan ~8 req/s)

Durante la indexacion se guarda:
- Metadata (nombre, tamaño, path, timestamps).
- Categoria detectada (manual, wiring, WinOLS, DAMOS, video curso, ...).
- Tags de vehiculo (marca, modelo, año, codigo ECU).
- Preview de texto (primeros 500 chars para archivos automotrices).
- Score automotriz (0..1).

Puedes cancelar en cualquier momento con el boton `Cancelar`. El
indice parcial queda guardado y se puede continuar con `Actualizar`.

---

## Paso 9 - Usar el Drive desde el AI Copilot

Una vez indexado, el AI Copilot puede:
- Buscar diagramas, pinouts y manuales relevantes al DTC actual.
- Sugerir mapas de tuning de tu coleccion para el ECU detectado.
- Citar el path exacto del archivo en Drive cuando da una respuesta.

No necesitas hacer nada adicional: la integracion es automatica a
traves de `/api/drive/search`.

---

## Actualizaciones incrementales

Cada vez que subas archivos nuevos al Drive haz clic en `Actualizar`
en la pagina Drive, o configura un cron que llame a
`POST /api/drive/index/incremental`. Solo se procesan archivos
modificados desde la ultima sincronizacion.

---

## Troubleshooting

**"No existe el archivo de credenciales"**
  Verifica que `config/google_credentials.json` existe y que SOLER se
  ejecuta desde la raiz del repo.

**"Error 403: access_denied"**
  Asegurate de haber agregado tu cuenta como `Test user` en la pantalla
  de consentimiento.

**"quotaExceeded"**
  Google Drive limita a ~1000 req/100s. El indexador ya usa rate
  limiting. Si igual lo ves, espera 2 minutos y reintenta con
  `Actualizar` (no `Indexar ahora`).

**Token corrupto / expirado**
  Borra `config/google_token.json` y vuelve a hacer clic en
  `Conectar Google Drive`.

**Quiero desconectar mi cuenta**
  Usa el boton `Desconectar` en la UI, o borra `google_token.json`.
  Tambien revoca el acceso en https://myaccount.google.com/permissions

---

## Privacidad

- Los scopes solicitados son SOLO de lectura (`drive.readonly` y
  `drive.metadata.readonly`). SOLER nunca modifica ni borra archivos.
- Todo el indice y el texto extraido vive en tu maquina local
  (`data/google_drive_index.db`).
- El token OAuth vive en `config/google_token.json`. Trata este archivo
  como una contraseña (agregalo a `.gitignore`).
