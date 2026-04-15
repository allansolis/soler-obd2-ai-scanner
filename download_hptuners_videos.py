"""
Descarga todos los videos de los cursos HP Tuners de autotech.
Los sube al Drive del usuario (2TB).

Usa yt-dlp con referer a hptuners.systeme.io (necesario para Vimeo protegido).
"""
import json
import subprocess
import sys
from pathlib import Path

CATALOG = Path("data/hptuners_courses.json")
DOWNLOAD_DIR = Path("D:/Herramientas/SOLER/hptuners_videos")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

RCLONE = "C:/Users/andre/AppData/Local/Microsoft/WinGet/Packages/Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe/rclone-v1.73.4-windows-amd64/rclone.exe"

with open(CATALOG) as f:
    data = json.load(f)

total_downloaded = 0
total_errors = 0

for course in data["courses"]:
    course_name = course["name"].replace("/", "_").replace(":", "_")
    course_dir = DOWNLOAD_DIR / course_name
    course_dir.mkdir(parents=True, exist_ok=True)
    course_url = course.get("url", "https://hptuners.systeme.io/")

    for lesson in course["lessons"]:
        title = lesson["title"].replace("/", "_")
        video_url = lesson["url"]
        video_id = lesson["video_id"]
        output_file = course_dir / f"{title}_{video_id}.mp4"

        if output_file.exists() and output_file.stat().st_size > 0:
            print(f"[SKIP] {course_name}/{title} ya existe")
            continue

        print(f"[DL] {course_name}/{title} ({video_url})...")
        try:
            result = subprocess.run([
                "yt-dlp",
                "--referer", course_url,
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "-o", str(output_file),
                "--no-warnings",
                video_url,
            ], capture_output=True, text=True, timeout=1800)
            if result.returncode == 0:
                total_downloaded += 1
                print(f"  [OK] {output_file.stat().st_size / 1024**2:.1f} MB")
                # Sync to Drive server-side
                subprocess.Popen([
                    RCLONE, "copy", str(output_file),
                    f"soler:SOLER_WORKSPACE/HPTUNERS_VIDEOS/{course_name}/",
                ])
            else:
                total_errors += 1
                print(f"  [ERROR] {result.stderr[-200:]}")
                if output_file.exists():
                    output_file.unlink()
        except subprocess.TimeoutExpired:
            total_errors += 1
            print(f"  [TIMEOUT]")

print(f"\n=== RESUMEN ===")
print(f"Videos descargados: {total_downloaded}")
print(f"Errores: {total_errors}")
print(f"Destino local: {DOWNLOAD_DIR}")
print(f"Destino Drive: SOLER_WORKSPACE/HPTUNERS_VIDEOS/")
