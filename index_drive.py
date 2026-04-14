"""Indexa el Drive completo al KnowledgeHub usando OAuth."""
import sys
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import sqlite3
from datetime import datetime

SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_authorized_user_file('config/google_token.json', SCOPES)
drive = build('drive', 'v3', credentials=creds)

AUTOMOTIVE_KEYWORDS = [
    'obd', 'dtc', 'ecu', 'tuning', 'mapa', 'bosch', 'delphi', 'mercedes', 'bmw',
    'toyota', 'nissan', 'mazda', 'honda', 'ford', 'vw', 'volkswagen', 'chevrolet',
    'hyundai', 'kia', 'manual', 'taller', 'scanner', 'diagnostico', 'winols',
    'ecm', 'pinout', 'autodata', 'mitchell', 'alldata', 'airbag', 'abs',
    'transmission', 'engine', 'motor', 'diesel', 'gasoline', 'injector', 'delphi',
    'dicatec', 'simplo', 'hp tuners', 'gds', 'gsic', 'etka', 'elsawin', 'wow',
    'dialogys', 'atsg', 'autotech', 'reparo', 'inmobilizador', 'fallas',
]

def is_automotive(name: str) -> bool:
    lower = name.lower()
    return any(kw in lower for kw in AUTOMOTIVE_KEYWORDS)

# Indexar Drive
print("Indexando Google Drive...")
conn = sqlite3.connect('data/knowledge_hub.db')
c = conn.cursor()

page_token = None
total = 0
automotive = 0
new_inserted = 0

while True:
    resp = drive.files().list(
        pageSize=1000,
        fields="nextPageToken, files(id, name, mimeType, size, parents, createdTime, modifiedTime, webViewLink)",
        pageToken=page_token,
        q="trashed=false",
    ).execute()
    files = resp.get('files', [])
    total += len(files)
    for f in files:
        if not is_automotive(f['name']):
            continue
        automotive += 1
        # Insertar al hub
        try:
            size = int(f.get('size', 0))
        except (ValueError, TypeError):
            size = 0
        link = f.get('webViewLink', f'https://drive.google.com/file/d/{f["id"]}/view')
        mime = f.get('mimeType', '')
        is_folder = mime == 'application/vnd.google-apps.folder'
        rtype = 'folder' if is_folder else (
            'pdf' if mime == 'application/pdf' else
            'archive' if mime in ('application/zip', 'application/x-rar-compressed') else
            'document'
        )
        try:
            c.execute("""
                INSERT OR IGNORE INTO resources
                (name, type, category, source, source_url, size_bytes, description, language, is_available_local, last_indexed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                f['name'], rtype, 'diagnostic' if 'diag' in f['name'].lower() else 'general',
                'google_drive', link, size,
                f'Indexado desde Drive el {datetime.now().isoformat()}',
                'es', False, datetime.now()
            ))
            if c.rowcount:
                new_inserted += 1
        except Exception as e:
            pass

    conn.commit()
    print(f"  ... procesados {total} archivos ({automotive} automotrices, {new_inserted} nuevos)")
    page_token = resp.get('nextPageToken')
    if not page_token:
        break

conn.close()
print(f"\n=== LISTO ===")
print(f"Total archivos en Drive: {total}")
print(f"Archivos automotrices encontrados: {automotive}")
print(f"Nuevos registros al KnowledgeHub: {new_inserted}")
