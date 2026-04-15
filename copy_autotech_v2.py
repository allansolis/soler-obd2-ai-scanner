"""
Copia server-side resiliente de carpetas AutoTech a Mi Drive.
- Retries automaticos en errores de red
- Continua si un archivo falla
- Checkpoint en JSON
"""
import json
import time
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import httplib2

SCOPES = ['https://www.googleapis.com/auth/drive']
creds = Credentials.from_authorized_user_file('config/google_token.json', SCOPES)

AUTOTECH_FOLDERS = [
    ("1LpAQ9825nNGLgrDV_eOXO0WJxTxiievV", "ALLDATA_2014"),
    ("1M_uTjPGCWKtXDHza1xmFPrw55LBBIBeK", "Diagramas_Electricos"),
    ("1FUQ-21tU4u_XRH2f3f4D8JHaYwt1G61a", "Manuales_Motor"),
    ("15cb6F0ZfidRrYvXJiJjxj5v3D6LAfsqM", "Manuales_Transmision"),
    ("1OK5XwQv0eYOmeSsxnOxUBBbBIV8E-bH7", "Manuales_Taller"),
    ("1NU1KVW50KOo9pQ4B9HZGI6vbqGjhxyPK", "Manuales_Usuario"),
    ("16c9uk3SaqwdSciCmf8SFP3OVXf_M36B9", "Marcas_America"),
    ("1u2BYkbFPWYQbOWer0rkNrGOC-i4P7NcJ", "Marcas_Asia"),
    ("1Wv1nAeGJg4EOu1otlEJzfsIRFfkUfHGb", "Marcas_Europa"),
    ("1Z5eRjHPbjyfw481CTN7aITz5ATZRealG", "Pinout_ECUs"),
    ("1CDSqNu4bf7QBWabt5fYIC8_CVNSos_Gy", "Pinout_Tableros"),
    ("1XefxSXZjmxK5cR5mR6tCPDHUBOBSkbGx", "Torque_Motores_Pesados"),
    ("1zeLhQJ-stLjHuOiLFmdG21ZUFDdFBxh-", "Manuales_Diagramas_Motos"),
    ("1CzH8XOQyOJMiUlJ5STg6T4NyOGtTQuNT", "Archivos_Variados"),
]

CHECKPOINT = Path("data/autotech_copy_checkpoint.json")
CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)


def get_drive():
    """Construye cliente Drive con timeout mayor."""
    return build('drive', 'v3', credentials=creds)


def load_checkpoint():
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"completed_folders": [], "copied_file_ids": {}}


def save_checkpoint(data):
    CHECKPOINT.write_text(json.dumps(data, indent=2))


def retry_api(func, *args, max_retries=5, **kwargs):
    """Ejecuta con retries."""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except (HttpError, httplib2.ServerNotFoundError, ConnectionError, OSError) as e:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt
            print(f"    [retry {attempt+1}/{max_retries}] {e} -> wait {wait}s")
            time.sleep(wait)


def find_or_create_folder(drive, name, parent_id):
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false"
    resp = retry_api(lambda: drive.files().list(q=q, fields="files(id)").execute())
    if resp.get('files'):
        return resp['files'][0]['id']
    folder = retry_api(lambda: drive.files().create(
        body={'name': name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]},
        fields='id',
    ).execute())
    return folder['id']


def list_children(drive, folder_id):
    items = []
    page_token = None
    while True:
        resp = retry_api(lambda: drive.files().list(
            pageSize=1000,
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken, files(id, name, mimeType, size)",
            pageToken=page_token,
        ).execute())
        items.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return items


def copy_file(drive, file_id, name, parent_id):
    try:
        retry_api(lambda: drive.files().copy(
            fileId=file_id,
            body={'name': name, 'parents': [parent_id]},
            fields='id',
        ).execute())
        return 'ok'
    except HttpError as e:
        if e.resp.status == 403:
            return 'forbidden'
        return 'error'
    except Exception:
        return 'error'


def copy_folder_recursive(drive, source_id, dest_id, checkpoint, depth=0):
    items = list_children(drive, source_id)
    stats = {'ok': 0, 'forbidden': 0, 'errors': 0, 'skipped': 0}
    for item in items:
        name = item['name']
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            sub_dest = find_or_create_folder(drive, name, dest_id)
            sub_stats = copy_folder_recursive(drive, item['id'], sub_dest, checkpoint, depth+1)
            for k in stats:
                stats[k] += sub_stats[k]
        else:
            # Skip si ya esta en checkpoint
            if item['id'] in checkpoint.get('copied_file_ids', {}):
                stats['skipped'] += 1
                continue
            result = copy_file(drive, item['id'], name, dest_id)
            if result == 'ok':
                stats['ok'] += 1
                checkpoint.setdefault('copied_file_ids', {})[item['id']] = True
                if stats['ok'] % 100 == 0:
                    save_checkpoint(checkpoint)
                    print(f"    {' '*depth}... {stats['ok']} copiados, {stats['skipped']} skipped, {stats['errors']} errors")
            elif result == 'forbidden':
                stats['forbidden'] += 1
            else:
                stats['errors'] += 1
    return stats


def main():
    drive = get_drive()
    checkpoint = load_checkpoint()

    # Root
    root_q = "name='SOLER_WORKSPACE' and mimeType='application/vnd.google-apps.folder' and 'root' in parents and trashed=false"
    root_resp = retry_api(lambda: drive.files().list(q=root_q, fields="files(id)").execute())
    if root_resp.get('files'):
        soler_root = root_resp['files'][0]['id']
    else:
        soler_root = retry_api(lambda: drive.files().create(
            body={'name': 'SOLER_WORKSPACE', 'mimeType': 'application/vnd.google-apps.folder'},
            fields='id'
        ).execute())['id']

    autotech_root = find_or_create_folder(drive, "AUTOTECH", soler_root)
    print(f"Destino: SOLER_WORKSPACE/AUTOTECH")

    total = {'ok': 0, 'forbidden': 0, 'errors': 0, 'skipped': 0}
    for folder_id, name in AUTOTECH_FOLDERS:
        if name in checkpoint.get('completed_folders', []):
            print(f"[DONE] {name} (checkpoint)")
            continue

        print(f"\n=== {name} ===")
        try:
            dest = find_or_create_folder(drive, name, autotech_root)
            t0 = time.time()
            stats = copy_folder_recursive(drive, folder_id, dest, checkpoint)
            elapsed = time.time() - t0
            print(f"  [OK] ok={stats['ok']} forbidden={stats['forbidden']} errors={stats['errors']} skipped={stats['skipped']} ({elapsed:.1f}s)")
            for k in total:
                total[k] += stats[k]
            checkpoint.setdefault('completed_folders', []).append(name)
            save_checkpoint(checkpoint)
        except Exception as e:
            print(f"  [FATAL] {e}")
            save_checkpoint(checkpoint)
            # Reintenta con nuevo cliente
            try:
                drive = get_drive()
            except Exception:
                pass

    print(f"\n=== TOTAL ===")
    print(f"  Copiados: {total['ok']}")
    print(f"  Forbidden: {total['forbidden']}")
    print(f"  Errors: {total['errors']}")
    print(f"  Skipped: {total['skipped']}")


if __name__ == "__main__":
    main()
