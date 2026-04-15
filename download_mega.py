"""Descarga link de Mega al Drive."""
import sys
import subprocess
from pathlib import Path
from mega import Mega

MEGA_URL = "https://mega.nz/file/prFjXL6L#Tbc1ezqB7Ozuk9DKZ4Bef9zP80GTqIQJ-vbYb4L89GM"
LOCAL_DIR = Path("D:/Herramientas/SOLER/mega_downloads")
LOCAL_DIR.mkdir(parents=True, exist_ok=True)

print(f"Descargando desde Mega...")
mega = Mega()
m = mega.login()  # anonymous
try:
    file = m.download_url(MEGA_URL, dest_path=str(LOCAL_DIR))
    print(f"[OK] Descargado: {file}")
    # Upload to Drive via rclone
    print("Subiendo a Mi Drive...")
    subprocess.run([
        "rclone", "copy", str(file),
        "soler:SOLER_WORKSPACE/MEGA_DOWNLOADS/",
        "--log-level", "INFO"
    ])
except Exception as e:
    print(f"[ERROR] {e}")
