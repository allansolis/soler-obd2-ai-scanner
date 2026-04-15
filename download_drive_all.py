"""
Descarga TODO el contenido automotriz del Drive a local.
Descarga en paralelo, con reanudacion y progreso.
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

DOWNLOAD_ROOT = Path("C:/Users/andre/OneDrive/Desktop/soler-obd2-ai-scanner/data/drive_downloads")
DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)

# IDs de las carpetas automotrices principales (de inventario)
AUTOMOTIVE_FOLDERS = {
    'ECM_PINOUT_8': '1NEnuccluC1CVE7BrHND7aD3N5aCiEPXT',
    'PROGRAMAS_AUTOMOTRICES': '1Ig8wg7J5Oe3nA3PX04431co_Us3lPQG_',
    # Las demas se descubren dinamicamente
}

# Keywords automotrices (para filtrado de "Compartido conmigo")
KEYWORDS = [
    'obd', 'dtc', 'ecu', 'tuning', 'mapa', 'bosch', 'delphi', 'mercedes', 'bmw',
    'toyota', 'nissan', 'mazda', 'honda', 'ford', 'vw', 'volkswagen', 'chevrolet',
    'hyundai', 'kia', 'manual', 'taller', 'scanner', 'diagnostico', 'winols',
    'ecm', 'pinout', 'autodata', 'mitchell', 'alldata', 'airbag', 'abs',
    'transmission', 'engine', 'motor', 'diesel', 'gasoline', 'injector',
    'dicatec', 'simplo', 'hp tuners', 'gds', 'gsic', 'etka', 'elsawin', 'wow',
    'dialogys', 'atsg', 'autotech', 'reparo', 'inmobilizador', 'fallas',
    'diagramas', 'electricos', 'mecanica', 'alfa', 'ultramate', 'tolerance',
    'mercado libre', 'tecnocar', 'papelnodigital', 'automotriz', 'immocode',
]


def is_automotive(name: str) -> bool:
    return any(kw in name.lower() for kw in KEYWORDS)


def human_size(bytes_val):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} PB"


def download_file(file_id: str, local_path: Path, expected_size: int = 0):
    """Descarga un archivo con progreso y reanudacion."""
    if local_path.exists() and expected_size > 0 and local_path.stat().st_size == expected_size:
        return 'skipped', local_path.stat().st_size

    local_path.parent.mkdir(parents=True, exist_ok=True)
    request = drive.files().get_media(fileId=file_id)

    try:
        with io.FileIO(local_path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=50 * 1024 * 1024)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return 'ok', local_path.stat().st_size
    except Exception as e:
        if local_path.exists():
            local_path.unlink()
        return 'error', str(e)


def list_all_shared_with_me():
    """Lista archivos y carpetas compartidos conmigo."""
    page_token = None
    items = []
    while True:
        resp = drive.files().list(
            pageSize=1000,
            q="sharedWithMe=true and trashed=false",
            fields="nextPageToken, files(id, name, mimeType, size, parents, owners)",
            pageToken=page_token,
        ).execute()
        items.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return items


def walk_folder(folder_id: str, base_path: Path, visited: set = None):
    """Recorre recursivamente una carpeta y retorna lista de archivos."""
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
            if f['mimeType'] == 'application/vnd.google-apps.folder':
                subfolder = base_path / f['name'].replace('/', '_')
                all_files.extend(walk_folder(f['id'], subfolder, visited))
            else:
                size = int(f.get('size', 0))
                all_files.append({
                    'id': f['id'],
                    'name': f['name'],
                    'size': size,
                    'local_path': base_path / f['name'],
                    'mimeType': f['mimeType'],
                })
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return all_files


def main(max_size_gb: float = 10.0, priority_only: bool = True):
    """Descarga archivos del Drive hasta un limite."""
    max_bytes = int(max_size_gb * 1024**3)

    print(f"Listando 'Compartido conmigo'...")
    shared = list_all_shared_with_me()
    print(f"  Total items compartidos: {len(shared)}")

    # Priorizar carpetas automotrices
    to_process = []
    for item in shared:
        if not is_automotive(item['name']):
            continue
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            base = DOWNLOAD_ROOT / item['name'].replace('/', '_')
            files = walk_folder(item['id'], base)
            to_process.extend(files)
        else:
            to_process.append({
                'id': item['id'],
                'name': item['name'],
                'size': int(item.get('size', 0)),
                'local_path': DOWNLOAD_ROOT / item['name'],
                'mimeType': item['mimeType'],
            })

    # Ordenar por tamano ascendente (descargar lo chico primero)
    to_process.sort(key=lambda f: f['size'])

    total_size = sum(f['size'] for f in to_process)
    print(f"\n  Total archivos automotrices: {len(to_process)}")
    print(f"  Tamano total estimado: {human_size(total_size)}")
    print(f"  Limite de descarga: {human_size(max_bytes)}")

    downloaded = 0
    bytes_downloaded = 0
    skipped = 0
    errors = []

    for i, f in enumerate(to_process, 1):
        if bytes_downloaded + f['size'] > max_bytes:
            print(f"\n  [LIMITE] Alcanzado {human_size(max_bytes)} - deteniendo")
            break

        print(f"  [{i}/{len(to_process)}] {f['name']} ({human_size(f['size'])})...", end=' ', flush=True)
        t0 = time.time()
        status, result = download_file(f['id'], f['local_path'], f['size'])
        elapsed = time.time() - t0

        if status == 'ok':
            downloaded += 1
            bytes_downloaded += result
            speed = result / elapsed / 1024**2 if elapsed > 0 else 0
            print(f"OK ({speed:.1f} MB/s)")
        elif status == 'skipped':
            skipped += 1
            bytes_downloaded += result
            print("SKIP (ya existe)")
        else:
            errors.append((f['name'], result))
            print(f"ERROR: {str(result)[:60]}")

    print(f"\n=== RESUMEN ===")
    print(f"Descargados: {downloaded}")
    print(f"Ya existian: {skipped}")
    print(f"Errores: {len(errors)}")
    print(f"Bytes totales: {human_size(bytes_downloaded)}")
    if errors:
        print(f"\nPrimeros errores:")
        for name, err in errors[:5]:
            print(f"  - {name}: {err[:80]}")


if __name__ == "__main__":
    # Por defecto: 10 GB max para primera pasada
    max_gb = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    main(max_size_gb=max_gb)
