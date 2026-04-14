"""Script rapido para autenticar con Google Drive y verificar acceso."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/drive.metadata.readonly',
]

CREDS = Path("config/google_credentials.json")
TOKEN = Path("config/google_token.json")


def main():
    print("=" * 60)
    print("SOLER OBD2 - Autenticacion Google Drive")
    print("=" * 60)

    if not CREDS.exists():
        print(f"\n[ERROR] No se encontro {CREDS}")
        sys.exit(1)

    creds = None
    if TOKEN.exists():
        print("\n[OK] Token existente encontrado, usando...")
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("\n[OK] Refrescando token...")
            creds.refresh(Request())
        else:
            print("\n[INFO] Abriendo navegador para autorizar...")
            print("[INFO] Inicia sesion con tu cuenta de Google y autoriza")
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS), SCOPES)
            creds = flow.run_local_server(port=8080, open_browser=True)

        TOKEN.parent.mkdir(parents=True, exist_ok=True)
        with open(TOKEN, 'w') as f:
            f.write(creds.to_json())
        print(f"\n[OK] Token guardado en {TOKEN}")

    print("\n[OK] Autenticacion exitosa")
    print("\nVerificando acceso al Drive...")

    service = build('drive', 'v3', credentials=creds)

    # Info del usuario
    about = service.about().get(fields='user,storageQuota').execute()
    user = about.get('user', {})
    quota = about.get('storageQuota', {})

    print(f"\nUsuario: {user.get('displayName')} ({user.get('emailAddress')})")
    total_gb = int(quota.get('limit', 0)) / (1024**3) if quota.get('limit') else 0
    used_gb = int(quota.get('usage', 0)) / (1024**3)
    print(f"Almacenamiento: {used_gb:.1f} GB / {total_gb:.1f} GB usado")

    # Contar archivos
    print("\nContando archivos en el Drive...")
    page_token = None
    count = 0
    pdf_count = 0
    folder_count = 0

    while True:
        results = service.files().list(
            pageSize=1000,
            fields="nextPageToken, files(mimeType)",
            pageToken=page_token,
        ).execute()
        files = results.get('files', [])
        count += len(files)
        for f in files:
            mt = f.get('mimeType', '')
            if mt == 'application/pdf':
                pdf_count += 1
            elif mt == 'application/vnd.google-apps.folder':
                folder_count += 1

        page_token = results.get('nextPageToken')
        if not page_token:
            break
        print(f"  ... {count} archivos contados", end='\r')

    print(f"\n\n=== RESUMEN ===")
    print(f"Total archivos: {count}")
    print(f"PDFs: {pdf_count}")
    print(f"Carpetas: {folder_count}")
    print(f"\n[OK] Integracion con Google Drive lista")
    print("     El AI Copilot ya puede usar tu Drive como base de conocimiento")


if __name__ == "__main__":
    main()
