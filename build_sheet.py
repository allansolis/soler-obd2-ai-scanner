"""
Construye la hoja SOLER en Google Sheets con plantillas de Claude for Sheets.
Crea una hoja nueva desde la app y la comparte con el usuario.
"""
import sys
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets',
]

CREDS = Path("config/google_credentials.json")
TOKEN = Path("config/google_token_sheets.json")
USER_EMAIL = "allann.solis.94@gmail.com"


def authenticate():
    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS), SCOPES)
            creds = flow.run_local_server(port=8080, open_browser=True)
        TOKEN.parent.mkdir(parents=True, exist_ok=True)
        with open(TOKEN, 'w') as f:
            f.write(creds.to_json())
    return creds


def main():
    print("Conectando con Google Sheets...")
    creds = authenticate()
    sheets = build('sheets', 'v4', credentials=creds)
    drive = build('drive', 'v3', credentials=creds)

    # 1. Crear spreadsheet nuevo con 5 tabs
    print("Creando hoja nueva...")
    spreadsheet_body = {
        'properties': {'title': 'SOLER OBD2 AI Scanner - Workspace'},
        'sheets': [
            {'properties': {'title': 'Dashboard', 'gridProperties': {'frozenRowCount': 1}}},
            {'properties': {'title': 'DTC Diagnostico', 'gridProperties': {'frozenRowCount': 1}}},
            {'properties': {'title': 'Perfiles Vehiculos', 'gridProperties': {'frozenRowCount': 1}}},
            {'properties': {'title': 'Tuning', 'gridProperties': {'frozenRowCount': 1}}},
            {'properties': {'title': 'Reparaciones', 'gridProperties': {'frozenRowCount': 1}}},
        ]
    }
    spreadsheet = sheets.spreadsheets().create(body=spreadsheet_body).execute()
    SHEET_ID = spreadsheet['spreadsheetId']
    print(f"[OK] Hoja creada: {SHEET_ID}")

    # 2. Dashboard
    dashboard_data = [
        ['SOLER OBD2 AI Scanner'],
        ['Workspace potenciado por Claude for Sheets'],
        [''],
        ['INSTRUCCIONES'],
        ['1. Instala la extension Claude for Sheets desde Extensiones > Complementos'],
        ['2. Configura tu API key en: Extensiones > Claude for Sheets > Enter API Key'],
        ['3. Ve a cada tab y completa los datos - Claude llenara las columnas automaticamente'],
        [''],
        ['TABS'],
        ['DTC Diagnostico: codigos DTC + Claude genera diagnostico, solucion y costo'],
        ['Perfiles Vehiculos: ingresa marca/modelo/anio y Claude completa perfil ECU'],
        ['Tuning: lecturas de sensores + Claude recomienda perfil de tuning'],
        ['Reparaciones: registro de ordenes con diagnostico AI'],
        [''],
        ['CONEXION CON SOLER'],
        ['Backend: http://localhost:8000/api/hub'],
        ['Frontend: http://localhost:3000'],
        ['Repo: https://github.com/allansolis/soler-obd2-ai-scanner'],
    ]
    sheets.spreadsheets().values().update(
        spreadsheetId=SHEET_ID, range='Dashboard!A1',
        valueInputOption='RAW', body={'values': dashboard_data}
    ).execute()
    print("[OK] Dashboard")

    # 3. DTC con formulas Claude
    dtc_data = [
        ['DTC', 'Marca', 'Modelo', 'Anio', 'Diagnostico AI', 'Solucion AI', 'Costo USD AI', 'Tiempo h AI'],
        ['P0420', 'Mercedes', 'C280', '2008',
         '=CLAUDE("Diagnostico tecnico para DTC "&A2&" en "&B2&" "&C2&" "&D2&". Max 80 palabras en espanol.")',
         '=CLAUDE("Solucion real para "&A2&" en "&B2&" "&C2&". Pasos concretos max 60 palabras.")',
         '=CLAUDE("Solo el costo USD min-max para reparar "&A2&" en "&B2&" "&C2&". Formato: $200-450")',
         '=CLAUDE("Solo numero de horas para reparar "&A2&". Ej: 2.5")'],
        ['P0300', 'Mazda', '6', '2004', '', '', '', ''],
        ['P0171', 'Toyota', 'Corolla', '2020', '', '', '', ''],
        ['P0128', 'Honda', 'Civic', '2018', '', '', '', ''],
        ['P0087', 'BMW', '330i', '2019', '', '', '', ''],
        ['P0011', 'Nissan', 'Altima', '2017', '', '', '', ''],
    ]
    sheets.spreadsheets().values().update(
        spreadsheetId=SHEET_ID, range='DTC Diagnostico!A1',
        valueInputOption='USER_ENTERED', body={'values': dtc_data}
    ).execute()
    print("[OK] DTC Diagnostico")

    # 4. Perfiles Vehiculos
    veh_data = [
        ['Marca', 'Modelo', 'Anio', 'Motor AI', 'ECU AI', 'Protocolo OBD AI', 'Fallas Comunes AI', 'Notas Tuning AI'],
        ['Mercedes-Benz', 'C280 W204', '2008',
         '=CLAUDE("Codigo motor del "&A2&" "&B2&" "&C2&". Solo el codigo. Ej: M272")',
         '=CLAUDE("ECU del "&A2&" "&B2&" "&C2&" motor "&D2&". Solo el nombre. Ej: Bosch ME9.7")',
         '=CLAUDE("Protocolo OBD del "&A2&" "&B2&" "&C2&". Solo nombre. Ej: ISO 15765-4 CAN")',
         '=CLAUDE("3 fallas comunes del "&A2&" "&B2&" "&C2&" motor "&D2&". Bullets en espanol.")',
         '=CLAUDE("Notas de tuning para "&A2&" "&B2&" "&C2&" motor "&D2&". Max 50 palabras.")'],
        ['Mazda', '6 GG1', '2004', '', '', '', '', ''],
        ['Toyota', 'Hilux 3.0', '2012', '', '', '', '', ''],
        ['BMW', '330i', '2019', '', '', '', '', ''],
        ['Nissan', 'Altima', '2017', '', '', '', '', ''],
    ]
    sheets.spreadsheets().values().update(
        spreadsheetId=SHEET_ID, range='Perfiles Vehiculos!A1',
        valueInputOption='USER_ENTERED', body={'values': veh_data}
    ).execute()
    print("[OK] Perfiles Vehiculos")

    # 5. Tuning
    tuning_data = [
        ['Marca', 'Modelo', 'Motor', 'HP Stock', 'Torque Stock', 'Perfil AI', 'HP Gain AI', 'Torque Gain AI', 'Riesgos AI'],
        ['Mercedes-Benz', 'C280', 'M272 3.0', 228, 300,
         '=CLAUDE("Para "&A2&" "&B2&" "&C2&" con "&D2&"HP/"&E2&"Nm, perfil seguro: Eco, Stage1, Sport o Stage2? Solo el nombre.")',
         '=CLAUDE("HP extra realistas stage1 para "&A2&" "&B2&" "&C2&". Solo numero.")',
         '=CLAUDE("Nm extra stage1 para "&A2&" "&B2&" "&C2&". Solo numero.")',
         '=CLAUDE("2 riesgos tunear "&A2&" "&B2&" "&C2&" stage1. Max 30 palabras.")'],
        ['Mazda', '6', 'L3-VE 2.3', 166, 207, '', '', '', ''],
        ['Toyota', 'Hilux', '2GD-FTV 2.4', 148, 400, '', '', '', ''],
    ]
    sheets.spreadsheets().values().update(
        spreadsheetId=SHEET_ID, range='Tuning!A1',
        valueInputOption='USER_ENTERED', body={'values': tuning_data}
    ).execute()
    print("[OK] Tuning")

    # 6. Reparaciones
    rep_data = [
        ['Fecha', 'Cliente', 'VIN', 'Vehiculo', 'DTC', 'Diagnostico AI', 'Accion', 'Horas', 'Costo USD', 'Estado'],
        ['2026-04-14', 'Cliente 1', 'WDBRF54J48B123456', 'Mercedes C280 2008', 'P0420',
         '=CLAUDE("Diagnostico breve "&E2&" en "&D2&". Max 25 palabras.")',
         '', '', '', 'Pendiente'],
    ]
    sheets.spreadsheets().values().update(
        spreadsheetId=SHEET_ID, range='Reparaciones!A1',
        valueInputOption='USER_ENTERED', body={'values': rep_data}
    ).execute()
    print("[OK] Reparaciones")

    # 7. Formato headers
    sheet_info = sheets.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    format_req = []
    for s in sheet_info['sheets']:
        sid = s['properties']['sheetId']
        format_req.append({
            'repeatCell': {
                'range': {'sheetId': sid, 'startRowIndex': 0, 'endRowIndex': 1},
                'cell': {'userEnteredFormat': {
                    'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
                    'backgroundColor': {'red': 0.05, 'green': 0.35, 'blue': 0.8},
                    'horizontalAlignment': 'CENTER'
                }},
                'fields': 'userEnteredFormat(textFormat,backgroundColor,horizontalAlignment)'
            }
        })
    sheets.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={'requests': format_req}).execute()
    print("[OK] Formato")

    # 8. Compartir con el usuario
    try:
        drive.permissions().create(
            fileId=SHEET_ID,
            body={'type': 'user', 'role': 'writer', 'emailAddress': USER_EMAIL},
            sendNotificationEmail=False
        ).execute()
        print(f"[OK] Compartido con {USER_EMAIL}")
    except Exception as e:
        print(f"[WARN] No se pudo compartir: {e}")

    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
    print(f"\n=== LISTO ===")
    print(f"URL: {url}")
    print(f"Tabs: Dashboard, DTC Diagnostico, Perfiles Vehiculos, Tuning, Reparaciones")


if __name__ == "__main__":
    main()
