# SOLER - Plantillas de Google Sheets

Archivos CSV listos para importar a Google Sheets con formulas de Claude for Sheets.

## Como usar

### Paso 1: Habilitar Google Sheets API (una sola vez)
Abre: https://console.developers.google.com/apis/api/sheets.googleapis.com/overview?project=524182963525

Click **HABILITAR**.

### Paso 2: Instalar Claude for Sheets
1. Abre cualquier hoja de Google Sheets
2. Menu **Extensiones > Complementos > Obtener complementos**
3. Busca "Claude for Sheets" de Anthropic
4. Click **Instalar**
5. Menu **Extensiones > Claude for Sheets > Open sidebar**
6. Pega tu API key de https://console.anthropic.com/settings/keys

### Paso 3: Importar plantillas
Para cada archivo CSV:
1. Abre Google Sheets nuevo: https://sheets.new
2. **Archivo > Importar > Subir** el CSV
3. Selecciona "Reemplazar hoja actual"
4. Marca **"Convertir texto a numeros, fechas y formulas"**
5. Importar

### Paso 4: Las formulas ejecutan automaticamente
Claude procesara cada fila y llenara las columnas de analisis.

## Plantillas incluidas

| Archivo | Proposito |
|---------|-----------|
| SOLER_DTC_Template.csv | Diagnostico de codigos DTC |
| SOLER_Perfiles_Vehiculos.csv | Perfil ECU + fallas + tuning |
| SOLER_Tuning.csv | Recomendacion de perfil tuning |

## Formulas principales

```
=CLAUDE("Diagnostico tecnico para DTC "&A2&" en "&B2&" "&C2)
=CLAUDE("Solucion real para "&A2&" en "&B2)
=CLAUDE("Solo el costo USD para reparar "&A2)
```
