"""
Launcher: ejecuta programas desde G:/H:/D: montados.
Permite al frontend lanzar software del Drive directamente.
"""
import subprocess
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/launcher", tags=["launcher"])


class LaunchRequest(BaseModel):
    path: str
    args: list[str] = []


class ExtractRequest(BaseModel):
    archive_path: str
    password: str = "DIGITALCONNECT"  # default clave 1
    destination: str = "D:/Herramientas/SOLER/extracted"


ALLOWED_ROOTS = ["G:", "H:", "D:/Herramientas/SOLER"]


def is_allowed(path: str) -> bool:
    """Verifica que la ruta este en los roots permitidos."""
    normalized = str(Path(path).resolve()).replace('\\', '/').rstrip('/')
    return any(normalized.startswith(r.replace('\\', '/').rstrip('/')) for r in ALLOWED_ROOTS)


@router.get("/drives")
def list_drives():
    """Lista los drives montados y su contenido top-level."""
    drives = []
    for letter, label in [("G:", "Mi Unidad"), ("H:", "Compartido conmigo"), ("D:", "Local")]:
        path = Path(letter + "/")
        if path.exists():
            try:
                items = [
                    {"name": p.name, "is_dir": p.is_dir(), "path": str(p).replace("\\", "/")}
                    for p in list(path.iterdir())[:50]
                ]
                drives.append({
                    "letter": letter,
                    "label": label,
                    "mounted": True,
                    "items": items,
                })
            except Exception as e:
                drives.append({"letter": letter, "label": label, "mounted": False, "error": str(e)})
    return drives


@router.get("/browse")
def browse(path: str):
    """Navega una carpeta del Drive montado."""
    if not is_allowed(path):
        raise HTTPException(403, "Path not allowed")
    p = Path(path)
    if not p.exists():
        raise HTTPException(404, "Path not found")
    if not p.is_dir():
        raise HTTPException(400, "Not a directory")

    items = []
    try:
        for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            try:
                size = child.stat().st_size if child.is_file() else 0
            except Exception:
                size = 0
            items.append({
                "name": child.name,
                "is_dir": child.is_dir(),
                "path": str(child).replace("\\", "/"),
                "size": size,
                "extension": child.suffix.lower() if child.is_file() else None,
            })
    except PermissionError:
        raise HTTPException(403, "Permission denied")
    return {"path": str(p).replace("\\", "/"), "items": items}


@router.post("/launch")
def launch_program(req: LaunchRequest):
    """Ejecuta un programa desde G:/H:/D:."""
    if not is_allowed(req.path):
        raise HTTPException(403, "Path not allowed")

    path = Path(req.path)
    if not path.exists():
        raise HTTPException(404, f"File not found: {req.path}")

    ext = path.suffix.lower()
    if ext not in ['.exe', '.msi', '.bat', '.cmd']:
        raise HTTPException(400, f"Unsupported extension: {ext}")

    try:
        # Ejecuta desacoplado
        subprocess.Popen(
            [str(path)] + req.args,
            shell=False,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
        return {"status": "launched", "path": str(path), "args": req.args}
    except Exception as e:
        raise HTTPException(500, f"Launch failed: {e}")


@router.post("/extract")
def extract_archive(req: ExtractRequest):
    """Extrae un .rar/.zip/.7z usando 7-Zip con password."""
    if not is_allowed(req.archive_path):
        raise HTTPException(403, "Path not allowed")

    archive = Path(req.archive_path)
    if not archive.exists():
        raise HTTPException(404, "Archive not found")

    dest = Path(req.destination) / archive.stem
    dest.mkdir(parents=True, exist_ok=True)

    seven_zip = "C:/Program Files/7-Zip/7z.exe"
    if not Path(seven_zip).exists():
        raise HTTPException(500, "7-Zip not installed")

    try:
        result = subprocess.run(
            [seven_zip, "x", f"-p{req.password}", "-y", str(archive), f"-o{dest}"],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if result.returncode != 0:
            raise HTTPException(500, f"Extract failed: {result.stderr[-500:]}")
        return {
            "status": "extracted",
            "destination": str(dest).replace("\\", "/"),
            "archive": req.archive_path,
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Extract timeout (30 min)")


@router.get("/software-catalog")
def software_catalog():
    """Lista software automotriz disponible via G:/H: con metadata."""
    catalog = []
    shared_root = Path("H:/")
    if not shared_root.exists():
        return {"error": "H: no montado", "items": []}

    # Buscar en carpetas conocidas
    targets = [
        ("H:/PROGRAMAS AUTOMOTRICES", "Software profesional"),
        ("H:/4LAP - Arquivos", "Tuning 4LAP"),
        ("H:/ECM PINOUT 8.0", "ECM PINOUT"),
    ]
    for folder_path, category in targets:
        folder = Path(folder_path)
        if not folder.exists():
            continue
        try:
            for item in folder.iterdir():
                if item.is_file() and item.suffix.lower() in ['.rar', '.zip', '.7z', '.exe', '.msi']:
                    try:
                        size = item.stat().st_size
                    except Exception:
                        size = 0
                    catalog.append({
                        "name": item.name,
                        "category": category,
                        "path": str(item).replace("\\", "/"),
                        "size": size,
                        "size_gb": round(size / 1024**3, 2),
                        "type": item.suffix.lower().lstrip('.'),
                        "needs_extract": item.suffix.lower() in ['.rar', '.zip', '.7z'],
                    })
        except PermissionError:
            continue

    return {"count": len(catalog), "items": catalog}
