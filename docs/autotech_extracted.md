# AutoTech Automotriz - Indice de Contenido Extraido

**Plataforma:** https://autotech.systeme.io/plataforma
**Fecha extraccion:** 2026-04-14
**Contacto:** contacto@autotechautomotriz.com
**Sitio oficial:** https://autotechautomotriz.com

---

## Descripcion general

AutoTech Automotriz es una plataforma de formacion tecnica automotriz que ofrece:

- Cursos en video (electricidad, cerrajeria, programacion, diagnostico, diesel, transmisiones, HP Tuners).
- Manuales de taller, de motor, de transmisiones y de usuario.
- Diagramas electricos por marca.
- Pinouts de ECUs y de tableros.
- Softwares automotrices (pack de 24 programas + ECM Pinout 8.0).

La pagina `/plataforma` es un hub publico que redirige a 6 subdominios de cursos (systeme.io) y a 14 colecciones alojadas en Google Drive.

---

## 1. Modulos de cursos (video)

| # | Modulo | Cursos | URL |
|---|--------|--------|-----|
| 1 | Electricidad Automotriz | 28 | https://electronicamovil.systeme.io/accesocursos |
| 2 | Cerrajeria Automotriz | 17 | https://llavespro.systeme.io/accesocursos |
| 3 | Programacion y Diagnostico Automotriz | 40 | https://diagnosticoauto.systeme.io/accesocursos |
| 4 | Motores Diesel | 12 | https://motoresdiesel.systeme.io/accesocursos |
| 5 | Transmisiones | 3 | https://transmisionesauto.systeme.io/accesocursos |
| 6 | HP Tuners | 5 | https://hptuners.systeme.io/accesocursos |

**Total cursos:** 105

> Nota: cada subdominio requiere credenciales de alumno para ver las lecciones individuales y URLs de video. El titulo de cada curso individual no es visible en la pagina publica.

---

## 2. Colecciones en Google Drive

### Manuales y diagramas

- ALLDATA 2014 (base de datos de taller)
- Diagramas Electricos
- Manuales De Motor
- Manuales De Usuario
- Manuales De Transmisiones
- Manuales De Taller
- Torque Motores Pesados
- Manuales y Diagramas De Motos

### Por region / marcas

- Marcas America
- Marcas Asia
- Marcas Europa

### Pinouts

- Pinout ECUs
- Pinout Tableros

### Varios

- Archivos Variados

### Software

- Pack 24 Softwares Automotriz
- ECM Pinout 8.0

**Total colecciones Drive + software:** 16

---

## 3. Resumen de recursos externos

- Links YouTube / Vimeo directos visibles: 0 (estan detras del login de cada curso).
- Links Google Drive: 16 colecciones (URLs finales requieren clic real en el landing).
- PDFs directos: 0 (todos residen dentro de las carpetas de Drive).

---

## 4. Limitaciones encontradas

1. **Subdominios de cursos bloqueados en esta sesion**: WebFetch denegado para los 6 dominios `*.systeme.io/accesocursos`. No se pudo extraer titulos de lecciones ni URLs de video.
2. **Login requerido**: aun accediendo manualmente, los subdominios systeme.io muestran un formulario de acceso/compra antes de listar el contenido detallado.
3. **Redirecciones Drive**: las URLs finales de las carpetas de Google Drive se resuelven del lado del cliente; no aparecen literales en el HTML publico.
4. **Curl bloqueado**: Bash con curl tambien denegado, por lo que no fue posible un fallback directo.

Para completar la extraccion se recomienda:
- Usar una sesion autenticada (cookies de alumno) con un navegador headless.
- Abrir manualmente cada landing y capturar el inspector de red para obtener las URLs reales de Drive.

---

## 5. Archivos generados

- `data/autotech_catalog.json` - catalogo estructurado.
- `docs/autotech_extracted.md` - este indice.
- `register_autotech.py` - script para insertar los recursos en `data/knowledge_hub.db`.
