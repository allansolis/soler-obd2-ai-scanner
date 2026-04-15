"""
Registra carpeta 4LAP Arquivos completa al KnowledgeHub.
Tambien descarga WinOLS v4.7 y PDF passo a passo.
"""
import io
import sqlite3
from datetime import datetime
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ['https://www.googleapis.com/auth/drive']
creds = Credentials.from_authorized_user_file('config/google_token.json', SCOPES)
drive = build('drive', 'v3', credentials=creds)

DOWNLOAD = Path("data/drive_downloads/4LAP")
DOWNLOAD.mkdir(parents=True, exist_ok=True)

MEGA_FOLDER = '1wY57MfifTjXkTDrMH-daf5_8EhAgwSyq'

# Walk recursivo
def walk(fid, path, result):
    page_token = None
    while True:
        resp = drive.files().list(
            pageSize=1000,
            q=f"'{fid}' in parents and trashed=false",
            fields='nextPageToken, files(id, name, mimeType, size, webViewLink)',
            pageToken=page_token,
        ).execute()
        for f in resp.get('files', []):
            if f['mimeType'] == 'application/vnd.google-apps.folder':
                walk(f['id'], path + '/' + f['name'], result)
            else:
                result.append({
                    'id': f['id'],
                    'name': f['name'],
                    'path': path,
                    'size': int(f.get('size', 0)),
                    'link': f.get('webViewLink', f'https://drive.google.com/file/d/{f["id"]}/view'),
                    'mime': f['mimeType'],
                })
        page_token = resp.get('nextPageToken')
        if not page_token:
            break

print("Inventariando 4LAP Arquivos completa...")
all_files = []
walk(MEGA_FOLDER, '4LAP', all_files)

# Stats
total_size = sum(f['size'] for f in all_files)
print(f"\nTotal archivos: {len(all_files)}")
print(f"Tamano total: {total_size / 1024**3:.2f} GB")

# Agrupar por carpeta
from collections import defaultdict
by_folder = defaultdict(lambda: {'count': 0, 'size': 0})
for f in all_files:
    # Primer nivel
    parts = f['path'].split('/')
    top = parts[1] if len(parts) > 1 else '(root)'
    by_folder[top]['count'] += 1
    by_folder[top]['size'] += f['size']

print(f"\nPor carpeta:")
for folder, stats in sorted(by_folder.items(), key=lambda x: -x[1]['size']):
    gb = stats['size'] / 1024**3
    print(f"  {folder}: {stats['count']} archivos, {gb:.2f} GB")

# Insertar al KnowledgeHub
print(f"\nInsertando al KnowledgeHub...")
conn = sqlite3.connect('data/knowledge_hub.db')
c = conn.cursor()
inserted = 0
for f in all_files:
    # Categoria basada en path
    path_lower = (f['path'] + '/' + f['name']).lower()
    if 'damos' in path_lower or 'mappack' in path_lower:
        category = 'tuning_maps'
    elif 'ecm titanium' in path_lower:
        category = 'tuning_software'
    elif 'winols' in path_lower:
        category = 'tuning_software'
    elif 'immo' in path_lower:
        category = 'immobilizer'
    elif 'truck' in path_lower or 'mercedes truck' in path_lower:
        category = 'truck_tuning'
    elif 'egr' in path_lower or 'dpf' in path_lower:
        category = 'emissions_delete'
    else:
        category = 'tuning'

    # Type
    name_lower = f['name'].lower()
    if name_lower.endswith(('.rar', '.zip', '.7z')):
        rtype = 'archive'
    elif name_lower.endswith('.pdf'):
        rtype = 'pdf'
    elif '.ols' in name_lower or 'stage' in name_lower or 'original' in name_lower:
        rtype = 'tuning_file'
    else:
        rtype = 'resource'

    try:
        c.execute("""
            INSERT OR IGNORE INTO resources
            (name, type, category, source, source_url, size_bytes, description, language, is_available_local, last_indexed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            f['name'][:200],
            rtype, category,
            'google_drive', f['link'],
            f['size'],
            f'Path: {f["path"]}'[:500],
            'pt', False, datetime.now().isoformat()
        ))
        if c.rowcount:
            inserted += 1
    except Exception as e:
        print(f"  error: {e}")

conn.commit()
conn.close()
print(f"  Nuevos registros: {inserted}")

# Descargar archivos claves
print(f"\nDescargando archivos clave...")
KEY_FILES = [
    ('WinOLS_v4.7_-_Contrase', 'WinOLS_v4.7.7z'),
    ('PASSO A PASSO DOS PROGRAMAS.pdf', 'passo_a_passo.pdf'),
]

for keyword, local_name in KEY_FILES:
    match = [f for f in all_files if keyword in f['name']]
    if not match:
        print(f"  [SKIP] No encontrado: {keyword}")
        continue
    f = match[0]
    local_path = DOWNLOAD / local_name
    if local_path.exists() and local_path.stat().st_size == f['size']:
        print(f"  [SKIP] Ya existe: {local_name}")
        continue
    print(f"  Descargando {local_name} ({f['size']/1024**2:.1f} MB)...", end=' ', flush=True)
    try:
        request = drive.files().get_media(fileId=f['id'])
        with io.FileIO(local_path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=50*1024*1024)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        print("OK")
    except Exception as e:
        print(f"ERROR: {e}")

print("\n=== LISTO ===")
