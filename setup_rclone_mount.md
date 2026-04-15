# Mount Google Drive como G: con rclone

## Paso 1: Verificar rclone instalado

```bash
rclone version
```

Si no funciona, reiniciar terminal (winget actualizo PATH).

## Paso 2: Configurar remote de Drive

```bash
rclone config
```

Responder:
- `n` (new remote)
- name: `soler`
- Storage: `17` (Google Drive) — el numero puede variar, elegir "Google Drive"
- client_id: dejar vacio (usa default de rclone)
- client_secret: dejar vacio
- scope: `1` (full access)
- service_account_file: vacio
- Edit advanced config: `n`
- Use auto config: `y` (abre navegador)
- Autorizar con `allann.solis.94@gmail.com`
- Configure as shared drive: `n`
- `y` (confirmar)
- `q` (quit)

## Paso 3: Instalar WinFSP (requerido para mount en Windows)

```bash
winget install WinFsp.WinFsp
```

Reinicia el terminal tras instalar.

## Paso 4: Montar Drive como G:

```bash
rclone mount soler: G: --vfs-cache-mode full --vfs-cache-max-size 20G --drive-chunk-size 64M --buffer-size 128M --dir-cache-time 1h
```

Drive aparece como G: en el explorador de Windows. Los .exe se pueden ejecutar directo.

## Paso 5: Auto-mount en Windows (para persistencia)

Crear `D:/Herramientas/SOLER/mount_drive.bat`:

```batch
@echo off
rclone mount soler: G: --vfs-cache-mode full --vfs-cache-max-size 20G --drive-chunk-size 64M
```

Agregar a Windows Startup via `.vbs`:

```vbs
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run chr(34) & "D:\Herramientas\SOLER\mount_drive.bat" & Chr(34), 0
Set WshShell = Nothing
```

## Uso en SOLER

Una vez montado G:\:
- Los programas del Drive aparecen como G:\ECM PINOUT 8.0\ECM PINOUT 8.0.part01.rar
- Al hacer click en un .exe, se ejecuta con streaming desde Drive
- Solo descarga las partes que accedes
- Cache local en ~/.config/rclone/cache/ (max 20GB)

## Integracion con el frontend de SOLER

El frontend puede lanzar programas asi:

```js
// Click en "HP TUNERS" en el KnowledgeHub
launchProgram({
  path: "G:\\PROGRAMAS AUTOMOTRICES\\HP TUNERS\\setup.exe"
});
```

Via un endpoint backend que ejecuta con subprocess.
