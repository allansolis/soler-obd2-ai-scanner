"""
Descarga TODO el contenido automotriz del Drive a D:/Herramientas/SOLER/
Reanuda si falla, prioriza por tamano, marca progreso.
"""
import io
import sys
import time
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ['https://www.googleapis.com/auth/drive']
creds = Credentials.from_authorized_user_file('config/google_token.json', SCOPES)
drive = build('drive', 'v3', credentials=creds)

DOWNLOAD_ROOT = Path("D:/Herramientas/SOLER/drive_downloads")
DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)

AUTOMOTIVE_KEYWORDS = [
    'obd', 'dtc', 'ecu', 'tuning', 'mapa', 'bosch', 'delphi', 'mercedes', 'bmw',
    'toyota', 'nissan', 'mazda', 'honda', 'ford', 'vw', 'volkswagen', 'chevrolet',
    'hyundai', 'kia', 'manual', 'taller', 'scanner', 'diagnostico', 'winols',
    'ecm', 'pinout', 'autodata', 'mitchell', 'alldata', 'airbag', 'abs',
    'transmission', 'engine', 'motor', 'diesel', 'gasoline', 'injector',
    'dicatec', 'simplo', 'hp tuners', 'gds', 'gsic', 'etka', 'elsawin', 'wow',
    'dialogys', 'atsg', 'autotech', 'reparo', 'inmobilizador', 'fallas',
    'diagramas', 'electricos', 'mecanica', 'alfa', 'ultramate', 'tolerance',
    'immo', 'truck', 'damos', 'mappack', 'egr', 'dpf', 'dsg', 'tdi', 'tfsi',
]


def is_automotive(name: str) -> bool:
    return any(kw in name.lower() for kw in AUTOMOTIVE_KEYWORDS)


def human(b):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def safe_name(name: str) -> str:
    """Reemplaza chars invalidos en Windows."""
    for bad in '<>:"|?*':
        name = name.replace(bad, '_')
    return name.strip()[:200]


def download_file(file_id, local_path, size_expected=0, retries=2):
    if local_path.exists() and size_expected > 0 and local_path.stat().st_size == size_expected:
        return 'skip', size_expected
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return 'error', f'mkdir: {e}'

    for attempt in range(retries):
        try:
            request = drive.files().get_media(fileId=file_id)
            with io.FileIO(local_path, 'wb') as fh:
                downloader = MediaIoBaseDownload(fh, request, chunksize=50*1024*1024)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
            return 'ok', local_path.stat().st_size
        except Exception as e:
            if local_path.exists():
                try:
                    local_path.unlink()
                except Exception:
                    pass
            if attempt == retries - 1:
                return 'error', str(e)[:100]
            time.sleep(2)


def walk_folder(folder_id, base_path, visited=None):
    if visited is None:
        visited = set()
    if folder_id in visited:
        return []
    visited.add(folder_id)

    all_files = []
    page_token = None
    while True:
        resp = drive.files().list(
            pageSize=1000,
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken, files(id, name, mimeType, size)",
            pageToken=page_token,
        ).execute()
        for f in resp.get('files', []):
            name_safe = safe_name(f['name'])
            if f['mimeType'] == 'application/vnd.google-apps.folder':
                all_files.extend(walk_folder(f['id'], base_path / name_safe, visited))
            else:
                # Skip Google Docs (they don't download as binary)
                if f['mimeType'].startswith('application/vnd.google-apps.'):
                    continue
                size = int(f.get('size', 0))
                if size == 0:
                    continue
                all_files.append({
                    'id': f['id'],
                    'name': f['name'],
                    'size': size,
                    'local_path': base_path / name_safe,
                    'mime': f['mimeType'],
                })
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return all_files


def list_shared_automotive():
    """Lista solo carpetas/archivos automotrices en Compartido conmigo."""
    page_token = None
    items = []
    while True:
        resp = drive.files().list(
            pageSize=1000,
            q="sharedWithMe=true and trashed=false",
            fields="nextPageToken, files(id, name, mimeType, size)",
            pageToken=page_token,
        ).execute()
        for f in resp.get('files', []):
            if is_automotive(f['name']):
                items.append(f)
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return items


def main(max_gb=100):
    print(f"Target: {DOWNLOAD_ROOT}")
    print(f"Limite: {max_gb} GB")
    print()

    print("Listando Compartido conmigo (solo automotriz)...")
    shared = list_shared_automotive()
    print(f"  {len(shared)} items automotrices en top-level")

    print("\nRecorriendo carpetas...")
    to_process = []
    for i, item in enumerate(shared, 1):
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            print(f"  [{i}/{len(shared)}] Walking: {item['name']}...", flush=True)
            base = DOWNLOAD_ROOT / safe_name(item['name'])
            files = walk_folder(item['id'], base)
            to_process.extend(files)
        else:
            size = int(item.get('size', 0))
            if size > 0:
                to_process.append({
                    'id': item['id'],
                    'name': item['name'],
                    'size': size,
                    'local_path': DOWNLOAD_ROOT / safe_name(item['name']),
                    'mime': item['mimeType'],
                })

    # Ordenar ascendente para maximizar numero de archivos descargados
    to_process.sort(key=lambda f: f['size'])
    total = sum(f['size'] for f in to_process)
    print(f"\n  {len(to_process)} archivos descargables, {human(total)}")

    max_bytes = int(max_gb * 1024**3)
    downloaded = skipped = errors = 0
    bytes_dl = 0

    for i, f in enumerate(to_process, 1):
        if bytes_dl + f['size'] > max_bytes:
            print(f"\n  Limite {max_gb} GB alcanzado")
            break
        print(f"  [{i}/{len(to_process)}] {f['name'][:60]} ({human(f['size'])})...", end=' ', flush=True)
        t0 = time.time()
        status, res = download_file(f['id'], f['local_path'], f['size'])
        el = time.time() - t0
        if status == 'ok':
            downloaded += 1
            bytes_dl += res
            spd = res / el / 1024**2 if el > 0 else 0
            print(f"OK ({spd:.1f} MB/s)")
        elif status == 'skip':
            skipped += 1
            bytes_dl += res
            print("SKIP")
        else:
            errors += 1
            print(f"ERR: {str(res)[:50]}")

    print(f"\n=== RESUMEN ===")
    print(f"Descargados: {downloaded}")
    print(f"Ya existian: {skipped}")
    print(f"Errores: {errors}")
    print(f"Total bytes: {human(bytes_dl)}")


if __name__ == "__main__":
    max_gb = float(sys.argv[1]) if len(sys.argv) > 1 else 100.0
    main(max_gb)
