"""
Copia los 16 Drive folders de AutoTech a Mi Drive usando Drive API.
Server-side copy (rapidisima).
"""
import sys
import time
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ['https://www.googleapis.com/auth/drive']
creds = Credentials.from_authorized_user_file('config/google_token.json', SCOPES)
drive = build('drive', 'v3', credentials=creds)

# Folder IDs descubiertos en autotech.systeme.io/plataforma
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


def find_or_create_folder(name, parent_id):
    """Busca o crea una carpeta dentro de parent_id."""
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false"
    resp = drive.files().list(q=q, fields="files(id)").execute()
    if resp.get('files'):
        return resp['files'][0]['id']
    folder = drive.files().create(
        body={
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id],
        },
        fields='id',
    ).execute()
    return folder['id']


def list_folder_contents(folder_id):
    """Lista recursivamente todo dentro de un folder ID."""
    items = []
    page_token = None
    while True:
        try:
            resp = drive.files().list(
                pageSize=1000,
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id, name, mimeType, size)",
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
            items.extend(resp.get('files', []))
            page_token = resp.get('nextPageToken')
            if not page_token:
                break
        except HttpError as e:
            print(f"  [ERR list] {e}")
            break
    return items


def copy_file_server_side(file_id, name, parent_id):
    """Copia server-side un archivo."""
    try:
        drive.files().copy(
            fileId=file_id,
            body={'name': name, 'parents': [parent_id]},
            fields='id',
            supportsAllDrives=True,
        ).execute()
        return True
    except HttpError as e:
        # 403 = no permission to copy (owner disabled)
        if e.resp.status == 403:
            return 'forbidden'
        return False


def copy_folder_recursive(source_folder_id, dest_parent_id, depth=0):
    """Copia recursivamente un folder entero."""
    items = list_folder_contents(source_folder_id)
    count = {'files': 0, 'folders': 0, 'errors': 0, 'forbidden': 0}

    for item in items:
        name = item['name']
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            # Crear subcarpeta y recurrir
            sub_id = find_or_create_folder(name, dest_parent_id)
            sub_count = copy_folder_recursive(item['id'], sub_id, depth+1)
            count['files'] += sub_count['files']
            count['folders'] += sub_count['folders'] + 1
            count['errors'] += sub_count['errors']
            count['forbidden'] += sub_count['forbidden']
        else:
            result = copy_file_server_side(item['id'], name, dest_parent_id)
            if result is True:
                count['files'] += 1
                if count['files'] % 50 == 0:
                    print(f"    {' '*depth}... {count['files']} archivos copiados")
            elif result == 'forbidden':
                count['forbidden'] += 1
            else:
                count['errors'] += 1
    return count


def main():
    print("Copia server-side de carpetas AutoTech a Mi Drive...")
    print()

    # Crear o encontrar raiz AUTOTECH en Mi Drive
    root_q = "name='SOLER_WORKSPACE' and mimeType='application/vnd.google-apps.folder' and 'root' in parents and trashed=false"
    root_resp = drive.files().list(q=root_q, fields="files(id)").execute()
    if root_resp.get('files'):
        soler_root = root_resp['files'][0]['id']
    else:
        folder = drive.files().create(
            body={'name': 'SOLER_WORKSPACE', 'mimeType': 'application/vnd.google-apps.folder'},
            fields='id'
        ).execute()
        soler_root = folder['id']

    autotech_root = find_or_create_folder("AUTOTECH", soler_root)
    print(f"Destino: SOLER_WORKSPACE/AUTOTECH (id={autotech_root})")
    print()

    total_stats = {'files': 0, 'folders': 0, 'errors': 0, 'forbidden': 0}
    for folder_id, name in AUTOTECH_FOLDERS:
        print(f"=== {name} ===")
        t0 = time.time()
        try:
            # Verificar acceso
            info = drive.files().get(fileId=folder_id, fields='id,name,owners').execute()
            print(f"  Accesible: {info['name']} - owner: {info.get('owners',[{}])[0].get('emailAddress','?')}")

            # Crear destino
            dest = find_or_create_folder(name, autotech_root)

            # Copiar recursivamente
            stats = copy_folder_recursive(folder_id, dest)
            elapsed = time.time() - t0
            print(f"  [OK] files={stats['files']} folders={stats['folders']} forbidden={stats['forbidden']} errors={stats['errors']} ({elapsed:.1f}s)")
            for k, v in stats.items():
                total_stats[k] += v
        except HttpError as e:
            print(f"  [ERR] {e}")

    print()
    print("=" * 50)
    print(f"TOTAL: archivos={total_stats['files']} carpetas={total_stats['folders']}")
    print(f"Permisos denegados (owner no permite copiar): {total_stats['forbidden']}")
    print(f"Errores: {total_stats['errors']}")


if __name__ == "__main__":
    main()
