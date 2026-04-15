"""
Verifica conexion + inventario completo + crea manifesto unificado del repositorio.
Genera data/drive_manifest.json con TODO lo disponible.
"""
import json
import time
from pathlib import Path
from collections import defaultdict
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_authorized_user_file('config/google_token.json', SCOPES)
drive = build('drive', 'v3', credentials=creds)

# 1. VERIFICAR CONEXION
print("="*60)
print("SOLER - Verificacion completa del repositorio unificado")
print("="*60)
print()
print("[1/5] Verificando conexion con Google Drive...")
about = drive.about().get(fields='user,storageQuota').execute()
user = about['user']
quota = about['storageQuota']
limit_gb = int(quota.get('limit', 0)) / 1024**3 if quota.get('limit') else 0
used_gb = int(quota.get('usage', 0)) / 1024**3
print(f"  [OK] Conectado: {user['displayName']} <{user['emailAddress']}>")
print(f"       Almacenamiento: {used_gb:.1f} / {limit_gb:.1f} GB ({used_gb*100/limit_gb:.1f}%)")
print()

# 2. INVENTARIAR TODO
print("[2/5] Inventariando TODO el Drive (Mi unidad + Compartido)...")

def list_all(query):
    results = []
    page_token = None
    while True:
        resp = drive.files().list(
            pageSize=1000,
            q=query,
            fields='nextPageToken, files(id, name, mimeType, size, parents, owners, createdTime, modifiedTime, webViewLink)',
            pageToken=page_token,
        ).execute()
        results.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return results

my_files = list_all("'me' in owners and trashed=false")
shared_files = list_all("sharedWithMe=true and trashed=false")
all_files = my_files + shared_files

print(f"  [OK] Mi unidad: {len(my_files)} items")
print(f"       Compartidos conmigo: {len(shared_files)} items")
print(f"       TOTAL: {len(all_files)} items")
print()

# 3. CATEGORIZAR
print("[3/5] Categorizando contenido...")

CATEGORIES = {
    'software_diagnostico': ['gds', 'gsic', 'ista', 'autocom', 'delphi', 'launch', 'foxwell', 'snap-on', 'autodata', 'mitchell', 'alldata', 'wow', 'simplo', 'dialogys', 'dicatec', 'scania', 'doutor-ie'],
    'software_tuning': ['winols', 'ecm titanium', 'hp tuners', 'kess', 'ktag', 'xprog', 'tl866'],
    'ecu_pinout': ['pinout', 'ecm pinout', 'pindata'],
    'immobilizer': ['immo', 'inmovilizador', 'key program'],
    'mapas_tuning': ['damos', 'mappack', 'mapa ', 'maps_', 'stage1', 'stage2', 'original'],
    'manuales_taller': ['manual', 'taller', 'workshop', 'service manual'],
    'diagramas_electricos': ['diagrama', 'electrico', 'wiring', 'pinout'],
    'obd_diesel': ['obd diesel', 'diesel', 'common rail'],
    'airbag_srs': ['airbag', 'srs'],
    'abs_esp': ['abs', 'esp', 'esc'],
    'transmission': ['transmission', 'atsg', 'caja automatica', 'dsg'],
    'emissions_delete': ['dpf', 'egr off', 'cat off', 'ad blue'],
    'truck_tuning': ['truck', 'scania', 'iveco', 'daf', 'volvo truck'],
    'catalogos': ['catalogo', 'epc', 'etka', 'elsawin'],
    'videos_cursos': ['curso', 'video', 'aula', 'capacit'],
    'pdfs_tecnicos': ['.pdf'],
    'archivos_comprimidos': ['.rar', '.zip', '.7z'],
    'ejecutables': ['.exe', '.msi'],
}

def categorize(name):
    lower = name.lower()
    cats = []
    for cat, keywords in CATEGORIES.items():
        if any(kw in lower for kw in keywords):
            cats.append(cat)
    return cats or ['otros']

categorized = defaultdict(list)
total_size_by_cat = defaultdict(int)

for f in all_files:
    name = f.get('name', '')
    size = int(f.get('size', 0))
    cats = categorize(name)
    for cat in cats:
        categorized[cat].append(f)
        total_size_by_cat[cat] += size

print(f"  [OK] Categorias detectadas: {len(categorized)}")
for cat, files in sorted(categorized.items(), key=lambda x: -total_size_by_cat[x[0]]):
    gb = total_size_by_cat[cat] / 1024**3
    print(f"       {cat:30s} {len(files):5d} items   {gb:8.2f} GB")
print()

# 4. GENERAR MANIFESTO UNIFICADO
print("[4/5] Generando manifesto unificado...")

manifest = {
    'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    'drive_user': user['emailAddress'],
    'drive_storage_gb': {'used': round(used_gb, 2), 'total': round(limit_gb, 2)},
    'total_items': len(all_files),
    'my_files_count': len(my_files),
    'shared_files_count': len(shared_files),
    'categories': {},
    'resources': [],
}

# Resources con categorias
for f in all_files:
    cats = categorize(f.get('name', ''))
    size = int(f.get('size', 0))
    is_folder = f.get('mimeType') == 'application/vnd.google-apps.folder'
    resource = {
        'id': f.get('id'),
        'name': f.get('name'),
        'mimeType': f.get('mimeType'),
        'size': size,
        'categories': cats,
        'is_folder': is_folder,
        'link': f.get('webViewLink'),
        'modified': f.get('modifiedTime'),
        'owner': f.get('owners', [{}])[0].get('emailAddress', '?'),
        'in_my_drive': f in my_files,
    }
    manifest['resources'].append(resource)

# Summary por categoria
for cat, files in categorized.items():
    manifest['categories'][cat] = {
        'count': len(files),
        'total_size_bytes': total_size_by_cat[cat],
        'total_size_gb': round(total_size_by_cat[cat] / 1024**3, 2),
    }

# Guardar
out_path = Path('data/drive_manifest.json')
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
print(f"  [OK] {out_path} ({out_path.stat().st_size / 1024**2:.1f} MB)")
print()

# 5. GENERAR INDICE LEGIBLE
print("[5/5] Generando indice legible (REPOSITORIO.md)...")

lines = [
    '# SOLER OBD2 AI Scanner - Repositorio Unificado',
    '',
    f'Generado: {manifest["generated_at"]}',
    f'Usuario: {manifest["drive_user"]}',
    f'Almacenamiento: {used_gb:.1f} / {limit_gb:.1f} GB',
    '',
    '## Resumen',
    '',
    f'- **Total items**: {len(all_files)}',
    f'- **En Mi unidad**: {len(my_files)}',
    f'- **Compartido conmigo**: {len(shared_files)}',
    '',
    '## Por categoria',
    '',
    '| Categoria | Items | Tamano |',
    '|-----------|-------|--------|',
]

for cat, info in sorted(manifest['categories'].items(), key=lambda x: -x[1]['total_size_bytes']):
    lines.append(f"| {cat} | {info['count']} | {info['total_size_gb']:.2f} GB |")

lines.extend(['', '## Top 20 items mas grandes', '', '| Nombre | Tamano | Categoria |', '|--------|--------|-----------|'])
biggest = sorted([r for r in manifest['resources'] if not r['is_folder']], key=lambda r: -r['size'])[:20]
for r in biggest:
    name = r['name'][:70].replace('|', '/')
    gb = r['size'] / 1024**3
    cats = ', '.join(r['categories'][:2])
    lines.append(f"| {name} | {gb:.2f} GB | {cats} |")

lines.extend(['', '## Integracion con SOLER', '',
              '- KnowledgeHub SQLite: `data/knowledge_hub.db`',
              '- PDFs locales analizados: `data/knowledge_extracted/pdf_analysis.json`',
              '- Drive manifest: `data/drive_manifest.json` (este documento en JSON)',
              '- Drive downloads: `D:/Herramientas/SOLER/drive_downloads/`',
              '',
              '## Acceso a programas',
              '',
              'Los programas se ejecutan de 3 formas:',
              '',
              '1. **Drive montado como G:**  (rclone mount) - ejecucion directa',
              '2. **Descarga on-demand** desde el frontend',
              '3. **Descarga completa** a `D:/Herramientas/SOLER/drive_downloads/`'])

with open('REPOSITORIO.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f"  [OK] REPOSITORIO.md generado")
print()

print("="*60)
print("VERIFICACION COMPLETA")
print("="*60)
print(f"  Drive conectado: OK")
print(f"  Items inventariados: {len(all_files)}")
print(f"  Categorias: {len(categorized)}")
print(f"  Manifesto: data/drive_manifest.json")
print(f"  Indice: REPOSITORIO.md")
