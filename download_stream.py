"""
Downloader streaming: descarga mientras explora (no espera walk completo).
Usa threads para descargar y explorar en paralelo.
"""
import io
import sys
import time
import threading
from queue import Queue
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ['https://www.googleapis.com/auth/drive']
creds = Credentials.from_authorized_user_file('config/google_token.json', SCOPES)
drive = build('drive', 'v3', credentials=creds)

DOWNLOAD_ROOT = Path("D:/Herramientas/SOLER/drive_downloads")
DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)

MAX_BYTES = int(float(sys.argv[1]) * 1024**3) if len(sys.argv) > 1 else 250 * 1024**3

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


def safe_name(n):
    for bad in '<>:"|?*':
        n = n.replace(bad, '_')
    return n.strip()[:200]


def human(b):
    for u in ['B', 'KB', 'MB', 'GB', 'TB']:
        if b < 1024:
            return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} PB"


def is_automotive(name):
    return any(kw in name.lower() for kw in AUTOMOTIVE_KEYWORDS)


download_queue = Queue()
stats = {'found': 0, 'downloaded': 0, 'skipped': 0, 'errors': 0, 'bytes': 0}
stats_lock = threading.Lock()
stop_flag = threading.Event()


def explorer_thread(folder_id, base_path, drive_local):
    """Thread que explora y agrega archivos al queue."""
    visited = set()

    def walk(fid, path):
        if fid in visited or stop_flag.is_set():
            return
        visited.add(fid)
        page_token = None
        while True:
            try:
                resp = drive_local.files().list(
                    pageSize=1000,
                    q=f"'{fid}' in parents and trashed=false",
                    fields="nextPageToken, files(id, name, mimeType, size)",
                    pageToken=page_token,
                ).execute()
            except Exception:
                break
            for f in resp.get('files', []):
                if stop_flag.is_set():
                    return
                name_safe = safe_name(f['name'])
                if f['mimeType'] == 'application/vnd.google-apps.folder':
                    walk(f['id'], path / name_safe)
                elif not f['mimeType'].startswith('application/vnd.google-apps.'):
                    size = int(f.get('size', 0))
                    if size > 0:
                        download_queue.put({
                            'id': f['id'], 'name': f['name'], 'size': size,
                            'local_path': path / name_safe,
                        })
                        with stats_lock:
                            stats['found'] += 1
            page_token = resp.get('nextPageToken')
            if not page_token:
                break

    walk(folder_id, base_path)


def downloader_thread(worker_id, drive_local):
    """Thread que consume del queue y descarga."""
    while not stop_flag.is_set():
        try:
            f = download_queue.get(timeout=2)
        except Exception:
            # Queue vacio por 2s - verifica si exploradores siguen
            if not any(t.is_alive() for t in explorer_threads):
                return
            continue

        with stats_lock:
            if stats['bytes'] + f['size'] > MAX_BYTES:
                stop_flag.set()
                return

        local_path = f['local_path']
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            with stats_lock:
                stats['errors'] += 1
            continue

        if local_path.exists() and local_path.stat().st_size == f['size']:
            with stats_lock:
                stats['skipped'] += 1
                stats['bytes'] += f['size']
            continue

        try:
            request = drive_local.files().get_media(fileId=f['id'])
            with io.FileIO(local_path, 'wb') as fh:
                downloader = MediaIoBaseDownload(fh, request, chunksize=25*1024*1024)
                done = False
                while not done and not stop_flag.is_set():
                    _, done = downloader.next_chunk()
            if stop_flag.is_set():
                return
            with stats_lock:
                stats['downloaded'] += 1
                stats['bytes'] += local_path.stat().st_size
        except Exception as e:
            if local_path.exists():
                try:
                    local_path.unlink()
                except Exception:
                    pass
            with stats_lock:
                stats['errors'] += 1


def reporter_thread():
    """Reporta progreso cada 10 segundos."""
    t0 = time.time()
    while not stop_flag.is_set():
        time.sleep(10)
        with stats_lock:
            elapsed = time.time() - t0
            rate = stats['bytes'] / elapsed / 1024**2 if elapsed > 0 else 0
            pct = stats['bytes'] * 100 / MAX_BYTES if MAX_BYTES else 0
            print(f"[{elapsed:.0f}s] Found={stats['found']} "
                  f"Dl={stats['downloaded']} Skip={stats['skipped']} "
                  f"Err={stats['errors']} | {human(stats['bytes'])} "
                  f"({pct:.1f}% of limit) | {rate:.1f} MB/s", flush=True)


# Main
print(f"Downloader streaming a {DOWNLOAD_ROOT}")
print(f"Limite: {human(MAX_BYTES)}")
print()

# Top-level automotive
print("Listando top-level compartido...")
shared_top = []
page_token = None
while True:
    resp = drive.files().list(
        pageSize=1000,
        q="sharedWithMe=true and trashed=false",
        fields="nextPageToken, files(id, name, mimeType, size)",
        pageToken=page_token,
    ).execute()
    for f in resp.get('files', []):
        if is_automotive(f['name']):
            shared_top.append(f)
    page_token = resp.get('nextPageToken')
    if not page_token:
        break

print(f"  Top-level automotrices: {len(shared_top)}")
print()

# Lanzar reporter
reporter = threading.Thread(target=reporter_thread, daemon=True)
reporter.start()

# Lanzar 4 downloaders
downloaders = []
for i in range(4):
    d_drive = build('drive', 'v3', credentials=creds)
    t = threading.Thread(target=downloader_thread, args=(i, d_drive), daemon=True)
    t.start()
    downloaders.append(t)

# Lanzar exploradores (uno por folder top-level)
explorer_threads = []
for item in shared_top:
    if item['mimeType'] == 'application/vnd.google-apps.folder':
        base = DOWNLOAD_ROOT / safe_name(item['name'])
        e_drive = build('drive', 'v3', credentials=creds)
        t = threading.Thread(target=explorer_thread, args=(item['id'], base, e_drive), daemon=True)
        t.start()
        explorer_threads.append(t)
    else:
        size = int(item.get('size', 0))
        if size > 0:
            download_queue.put({
                'id': item['id'], 'name': item['name'], 'size': size,
                'local_path': DOWNLOAD_ROOT / safe_name(item['name']),
            })
            with stats_lock:
                stats['found'] += 1

# Esperar exploradores
for t in explorer_threads:
    t.join()
print("\n[Exploradores terminaron]")

# Esperar downloaders
for t in downloaders:
    t.join()
print("\n[Downloaders terminaron]")

print(f"\n=== FINAL ===")
print(f"Found: {stats['found']}")
print(f"Downloaded: {stats['downloaded']}")
print(f"Skipped: {stats['skipped']}")
print(f"Errors: {stats['errors']}")
print(f"Bytes: {human(stats['bytes'])}")
