"""
test_backup_rendimiento.py
Valida:
  1. Backup automático en disco ANTES de la primera modificación
  2. Mapas de rendimiento (lambda/AFR, VVT, knock, rev_limit) por marca
  3. Integración ECUReader.load_performance_maps() con backup activado

Ejecutar:  python test_backup_rendimiento.py
"""
import sys
import io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import json
import shutil
import tempfile
import traceback
from pathlib import Path

import numpy as np

# ── Colores ─────────────────────────────────────────────────────────────────────
R="\033[91m"; G="\033[92m"; Y="\033[93m"; B="\033[94m"
M="\033[95m"; W="\033[97m"; RESET="\033[0m"; BOLD="\033[1m"
PASS=0; FAIL=0

def ok(m):   print(f"{G}  ✓ {m}{RESET}")
def err(m):  print(f"{R}  ✗ {m}{RESET}")
def warn(m): print(f"{Y}  ⚠ {m}{RESET}")
def head(m): print(f"\n{BOLD}{B}{m}{RESET}")
def sub(m):  print(f"{M}  ── {m}{RESET}")

def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; ok(f"{label}{' — '+detail if detail else ''}")
    else:
        FAIL += 1; err(f"{label}{' — '+detail if detail else ''}")


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1 — BACKUP AUTOMÁTICO (MapTable + MapEditor)
# ═══════════════════════════════════════════════════════════════════════════════

def test_backup_automatico():
    from scaner_soler.ecu.maps.map_table import MapTable
    from scaner_soler.ecu.maps.map_editor import MapEditor
    from scaner_soler.exceptions import SafetyError

    head("BACKUP AUTOMÁTICO ANTES DE MODIFICACIÓN")

    tmp = Path(tempfile.mkdtemp(prefix="ss_backup_test_"))
    try:
        rpm  = np.array([800,1200,2000,3000,4000,5500], dtype=float)
        load = np.array([20,40,60,80,100], dtype=float)
        vals = np.full((6, 5), 20.0)

        tabla = MapTable(
            name="ignition_test",
            rpm_axis=rpm, load_axis=load, values=vals.copy(),
            unit="deg BTDC", min_safe=-5.0, max_safe=40.0,
        )

        sub("Sin backup habilitado")
        check("file_backup_path es None antes de habilitar",
              tabla.file_backup_path is None)

        # Habilitar auto-backup
        tabla.enable_auto_backup(tmp, vin="WVWTEST123456")
        check("auto_backup_dir asignado", tabla._auto_backup_dir == tmp)
        check("file_backup_path aún None (no se modificó nada)",
              tabla.file_backup_path is None)

        checksum_original = tabla.checksum()

        sub("Primera modificación → debe crear backup")
        tabla.set_cell(0, 0, 22.0)
        bp = tabla.file_backup_path
        check("file_backup_path creado tras set_cell()",
              bp is not None, str(bp))
        check("Archivo existe en disco", bp is not None and bp.exists())

        if bp and bp.exists():
            saved = json.loads(bp.read_text(encoding="utf-8"))
            check("JSON contiene clave 'name'",   "name" in saved)
            check("JSON contiene clave 'values'", "values" in saved)
            check("_backup_meta.type == 'pre_modification'",
                  saved.get("_backup_meta", {}).get("type") == "pre_modification")
            check("_backup_meta.vin == 'WVWTEST123456'",
                  saved.get("_backup_meta", {}).get("vin") == "WVWTEST123456")
            check("Checksum en backup == checksum original pre-edición",
                  saved["_backup_meta"]["checksum_before"] == checksum_original)
            # Verificar que el backup tiene los valores ORIGINALES (antes del set_cell)
            saved_val = saved["values"][0][0]
            check(f"Backup tiene valor original {saved_val:.1f} (no el nuevo 22.0)",
                  abs(saved_val - 20.0) < 1e-9)

        sub("Segunda modificación → NO crea otro backup")
        bp_antes = tabla.file_backup_path
        tabla.set_cell(1, 1, 23.0)
        check("file_backup_path no cambió en segunda edición",
              tabla.file_backup_path == bp_antes)

        sub("set_region() también usa el mismo backup")
        tabla2 = MapTable(
            name="fuel_test",
            rpm_axis=rpm, load_axis=load,
            values=np.full((6,5), 5.0),
            unit="ms", min_safe=0.5, max_safe=20.0,
        )
        tabla2.enable_auto_backup(tmp, vin="TOYOTA99")
        tabla2.set_region(slice(0,3), slice(0,3), 0.5)
        check("set_region() creó backup en disco",
              tabla2.file_backup_path is not None and
              tabla2.file_backup_path.exists())

        sub("MapEditor.enable_auto_backup() delega en MapTable")
        tabla3 = MapTable(
            name="boost_test",
            rpm_axis=rpm, load_axis=load,
            values=np.full((6,5), 1.2),
            unit="bar abs", min_safe=0.8, max_safe=2.5,
        )
        editor = MapEditor(tabla3)
        editor.enable_auto_backup(tmp, vin="BMWTEST001")
        check("backup_info.auto_backup_enabled == True",
              editor.backup_info["auto_backup_enabled"])
        check("backup_info.backup_exists == False (aún sin editar)",
              not editor.backup_info["backup_exists"])
        editor.set(0, 0, 1.4)
        check("backup_info.backup_exists == True tras edición",
              editor.backup_info["backup_exists"])
        check("backup_info.vin == 'BMWTEST001'",
              editor.backup_info["vin"] == "BMWTEST001")

        sub("Restaurar desde backup en disco")
        saved_path = tabla.file_backup_path
        if saved_path and saved_path.exists():
            from scaner_soler.ecu.maps.map_table import MapTable as MT
            restored = MT.from_dict(json.loads(saved_path.read_text(encoding="utf-8")))
            check("MapTable.from_dict() del backup restaura valores originales",
                  abs(restored.get_cell(0, 0) - 20.0) < 1e-9)
            check("Nombre del mapa restaurado correcto",
                  restored.name == "ignition_test")

        # Listar backups creados
        backups = list(tmp.glob("*.json"))
        check(f"Al menos 3 archivos .json en backup_dir ({len(backups)})",
              len(backups) >= 3)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2 — MAPAS DE RENDIMIENTO (PERFORMANCE_MAP_DEFS)
# ═══════════════════════════════════════════════════════════════════════════════

def test_mapas_rendimiento():
    from scaner_soler.ecu.ecu_reader import PERFORMANCE_MAP_DEFS
    from scaner_soler.ecu.maps.map_table import MapTable
    from scaner_soler.ecu.maps.map_editor import MapEditor
    from scaner_soler.exceptions import SafetyError

    head("MAPAS DE RENDIMIENTO — LAMBDA / VVT / KNOCK / REV_LIMIT")

    EXPECTED_MAPS = {
        "VW_Bosch_ME17":    ["lambda_target", "vvt_intake", "knock_retard"],
        "Toyota_Denso":     ["lambda_target", "vvt_intake", "vvt_exhaust"],
        "BMW_Bosch_MSD80":  ["lambda_target", "vvt_intake", "vvt_exhaust", "knock_retard"],
        "Ford_PCM":         ["lambda_target", "rev_limit"],
        "Chevrolet_Delphi_E38": ["lambda_target", "knock_retard"],
        "Honda_Keihin":     ["lambda_target", "vvt_intake"],
        "Nissan_Hitachi":   ["lambda_target", "vvt_intake"],
        "Renault_Siemens":  ["lambda_target"],
    }

    for brand, expected in EXPECTED_MAPS.items():
        sub(f"{brand}")
        brand_defs = PERFORMANCE_MAP_DEFS.get(brand)
        check(f"[{brand}] presente en PERFORMANCE_MAP_DEFS", brand_defs is not None)
        if brand_defs is None:
            continue

        for map_name in expected:
            defn = brand_defs.get(map_name)
            check(f"[{brand}/{map_name}] definición presente", defn is not None)
            if defn is None:
                continue

            # Construir MapTable con valores base
            rpm_axis  = np.array(defn["rpm_axis"], dtype=float)
            load_axis = np.array(defn["load_axis"], dtype=float)
            rows, cols = len(rpm_axis), len(load_axis)
            base = float(defn["base"])
            values = np.full((rows, cols), base)

            tabla = MapTable(
                name=f"{brand}_{map_name}",
                rpm_axis=rpm_axis,
                load_axis=load_axis,
                values=values,
                unit=defn["unit"],
                min_safe=defn["min_safe"],
                max_safe=defn["max_safe"],
                description=defn["description"],
            )
            check(f"[{brand}/{map_name}] shape ({rows}x{cols}) correcto",
                  tabla.values.shape == (rows, cols))

            # Rango seguro corresponde al tipo
            if map_name == "lambda_target":
                check(f"[{brand}/{map_name}] lambda min >= 0.75",
                      defn["min_safe"] >= 0.75)
                check(f"[{brand}/{map_name}] lambda max <= 1.10",
                      defn["max_safe"] <= 1.10)
                check(f"[{brand}/{map_name}] enriquecimiento WOT < 1.0",
                      defn.get("wot_enrich", 0.89) < 1.0)
            elif map_name in ("vvt_intake", "vvt_exhaust"):
                check(f"[{brand}/{map_name}] min VVT == 0",
                      defn["min_safe"] == 0.0)
                check(f"[{brand}/{map_name}] max VVT entre 25-65 deg",
                      25.0 <= defn["max_safe"] <= 65.0)
            elif map_name == "knock_retard":
                check(f"[{brand}/{map_name}] min retardo == 0",
                      defn["min_safe"] == 0.0)
                check(f"[{brand}/{map_name}] max retardo <= 15 deg",
                      defn["max_safe"] <= 15.0)
            elif map_name == "rev_limit":
                check(f"[{brand}/{map_name}] límite max > 4000 RPM",
                      defn["max_safe"] > 4000.0)

            # Edición con SafetyError
            editor = MapEditor(tabla)
            unsafe = defn["max_safe"] + 1.0
            raised = False
            try:
                editor.set(0, 0, unsafe)
            except SafetyError:
                raised = True
            check(f"[{brand}/{map_name}] SafetyError en valor {unsafe:.2f} {defn['unit']}",
                  raised)

            # Edición segura
            safe = (defn["min_safe"] + defn["max_safe"]) / 2.0
            try:
                editor.set(0, 0, safe)
                check(f"[{brand}/{map_name}] set() valor central seguro ({safe:.3f})",
                      abs(tabla.get_cell(0,0) - safe) < 1e-9)
            except Exception as e:
                check(f"[{brand}/{map_name}] set() central", False, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3 — ECUReader.load_performance_maps() con backup automático
# ═══════════════════════════════════════════════════════════════════════════════

def test_ecu_reader_performance():
    from scaner_soler.ecu.ecu_reader import ECUReader, PERFORMANCE_MAP_DEFS
    from scaner_soler.ecu.maps.map_editor import MapEditor
    from scaner_soler.exceptions import SafetyError
    from scaner_soler.comm.vehicle_conn import VehicleConnection
    from scaner_soler.comm.base import AbstractProtocol, DTC

    head("ECUReader.load_performance_maps() — BACKUP + EDICIÓN")

    # Mock mínimo para VehicleConnection
    class MockProto(AbstractProtocol):
        def connect(self, port="MOCK", baudrate=115200) -> bool: return True
        def disconnect(self): pass
        @property
        def is_connected(self) -> bool: return True
        def send_raw(self, data: bytes, timeout=5.0) -> bytes: return b"\x00"
        def read_pid(self, pid: int, mode: int = 0x01) -> dict:
            return {"value": 0.0, "unit": "", "name": f"pid_{pid:02X}"}
        def read_dtc(self) -> list: return []
        def clear_dtc(self) -> bool: return True
        def read_freeze_frame(self, dtc_code: str) -> dict: return {}
        def read_vehicle_info(self) -> dict:
            return {"vin": "TESTVIN12345678901", "ecu_name": "MockECU"}

    tmp = Path(tempfile.mkdtemp(prefix="ss_perf_test_"))
    try:
        conn   = VehicleConnection(protocol=MockProto())
        reader = ECUReader(conn, vin="BMWTEST001")
        reader_backups = tmp  # redireccionar backups al temp

        # Redireccionar BACKUPS_DIR solo para el test
        import scaner_soler.ecu.ecu_reader as ecu_mod
        orig_backups = ecu_mod.BACKUPS_DIR
        ecu_mod.BACKUPS_DIR = tmp
        tmp.mkdir(parents=True, exist_ok=True)

        try:
            MARCAS_TEST = ["VW_Bosch_ME17", "Toyota_Denso", "BMW_Bosch_MSD80",
                           "Ford_PCM", "Chevrolet_Delphi_E38", "Honda_Keihin",
                           "Nissan_Hitachi", "Renault_Siemens"]

            for brand in MARCAS_TEST:
                sub(f"{brand}")
                try:
                    maps = reader.load_performance_maps(brand, auto_backup=True)
                    check(f"[{brand}] retorna dict no vacío", len(maps) >= 1)

                    for map_name, tabla in maps.items():
                        check(f"[{brand}/{map_name}] auto_backup habilitado",
                              tabla._auto_backup_dir is not None)
                        check(f"[{brand}/{map_name}] aún sin backup (no editado)",
                              tabla.file_backup_path is None)

                        # Primer edit → dispara backup
                        editor = MapEditor(tabla)
                        safe_val = (tabla.min_safe + tabla.max_safe) / 2.0
                        editor.set(0, 0, safe_val)

                        check(f"[{brand}/{map_name}] backup creado tras edición",
                              tabla.file_backup_path is not None and
                              tabla.file_backup_path.exists())

                        # Segundo edit → no duplica backup
                        bp_1 = tabla.file_backup_path
                        editor.set(0, 0, safe_val + 0.001
                                   if safe_val + 0.001 <= tabla.max_safe else safe_val)
                        check(f"[{brand}/{map_name}] backup no se duplica",
                              tabla.file_backup_path == bp_1)

                except ValueError as e:
                    check(f"[{brand}] load_performance_maps() sin ValueError", False, str(e))
                except Exception as e:
                    check(f"[{brand}] load_performance_maps()", False, str(e))
                    traceback.print_exc()

            # Marca inválida lanza ValueError
            raised = False
            try:
                reader.load_performance_maps("Marca_Inexistente")
            except ValueError:
                raised = True
            check("ValueError para marca desconocida", raised)

            # Contar backups generados
            backups = list(tmp.glob("*_PREMOD.json"))
            total_expected_maps = sum(
                len(PERFORMANCE_MAP_DEFS[b]) for b in MARCAS_TEST
            )
            check(f"Backups en disco == total mapas editados ({len(backups)}/{total_expected_maps})",
                  len(backups) == total_expected_maps,
                  f"encontrados {len(backups)}")

            # Verificar integridad de un backup aleatorio
            if backups:
                sample = json.loads(backups[0].read_text(encoding="utf-8"))
                check("Backup contiene _backup_meta",   "_backup_meta" in sample)
                check("Backup contiene values",         "values" in sample)
                check("Backup contiene rpm_axis",       "rpm_axis" in sample)
                check("Backup meta.type == 'pre_modification'",
                      sample["_backup_meta"]["type"] == "pre_modification")

        finally:
            ecu_mod.BACKUPS_DIR = orig_backups

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 4 — FLUJO COMPLETO: cargar mapa performance → editar → save_map_profile
# ═══════════════════════════════════════════════════════════════════════════════

def test_flujo_completo_rendimiento():
    from scaner_soler.ecu.ecu_reader import ECUReader, PERFORMANCE_MAP_DEFS
    from scaner_soler.ecu.maps.map_editor import MapEditor
    from scaner_soler.comm.vehicle_conn import VehicleConnection
    from scaner_soler.comm.base import AbstractProtocol

    head("FLUJO COMPLETO: LOAD → BACKUP → EDICIÓN → SAVE PROFILE")

    class MockProto(AbstractProtocol):
        def connect(self, port="MOCK", baudrate=115200) -> bool: return True
        def disconnect(self): pass
        @property
        def is_connected(self) -> bool: return True
        def send_raw(self, data: bytes, timeout=5.0) -> bytes: return b"\x00"
        def read_pid(self, pid, mode=0x01) -> dict:
            return {"value": 0.0, "unit": "", "name": f"pid_{pid:02X}"}
        def read_dtc(self): return []
        def clear_dtc(self) -> bool: return True
        def read_freeze_frame(self, code) -> dict: return {}
        def read_vehicle_info(self) -> dict:
            return {"vin": "WVWTEST1234567890A", "ecu_name": "Bosch ME17"}

    tmp = Path(tempfile.mkdtemp(prefix="ss_flow_test_"))
    try:
        import scaner_soler.ecu.ecu_reader as ecu_mod
        orig_b = ecu_mod.BACKUPS_DIR
        orig_m = ecu_mod.MAPS_DIR
        ecu_mod.BACKUPS_DIR = tmp / "backups"
        ecu_mod.MAPS_DIR    = tmp / "maps"
        (tmp / "backups").mkdir(); (tmp / "maps").mkdir()

        try:
            conn   = VehicleConnection(protocol=MockProto())
            reader = ECUReader(conn, vin="WVWTEST1234567890A")

            # 1. Cargar mapas de rendimiento VW
            maps = reader.load_performance_maps("VW_Bosch_ME17", auto_backup=True)
            check("load_performance_maps('VW') retorna mapas", len(maps) >= 3)

            # 2. Editar lambda_target: enriquecer WOT
            if "lambda_target" in maps:
                tabla  = maps["lambda_target"]
                editor = MapEditor(tabla)
                # Columna 7 = carga 80%, columna 8 = 90%, columna 9+ = WOT
                cols = len(tabla.load_axis)
                for col in range(max(0, cols-2), cols):
                    try:
                        editor.set(0, col, 0.87)  # enriquecimiento WOT
                    except Exception:
                        pass
                check("lambda_target editado (enriquecimiento WOT)",
                      tabla.has_changes)
                check("Backup creado tras edición lambda",
                      tabla.file_backup_path is not None)

            # 3. Editar vvt_intake: +5 deg a RPM medias
            if "vvt_intake" in maps:
                tabla_vvt = maps["vvt_intake"]
                editor_vvt = MapEditor(tabla_vvt)
                try:
                    editor_vvt.add_to_region(slice(3,6), slice(1,4), 3.0)
                except Exception as e:
                    warn(f"vvt_intake add_to_region: {e}")
                check("vvt_intake modificado", tabla_vvt.has_changes)

            # 4. Guardar perfil de rendimiento completo
            saved_path = reader.save_map_profile(
                maps,
                profile_name="rendimiento_stage1",
                dyno_results={"hp": 315, "tq_nm": 450, "rpm_peak": 5400},
            )
            check("save_map_profile() crea archivo .ssmap",
                  saved_path.exists() and saved_path.suffix == ".ssmap")

            # 5. Recargar perfil y verificar
            maps_reloaded = reader.load_map_profile(saved_path)
            check("load_map_profile() devuelve mismas tablas",
                  set(maps_reloaded.keys()) == set(maps.keys()))
            if "lambda_target" in maps_reloaded:
                tbl_r = maps_reloaded["lambda_target"]
                check("lambda_target name preservado tras roundtrip",
                      "lambda_target" in tbl_r.name)

            # 6. Inventario de backups generados
            backups = list((tmp / "backups").glob("*_PREMOD.json"))
            check(f"Backups en disco tras flujo completo (>= 2): {len(backups)}",
                  len(backups) >= 2)

        finally:
            ecu_mod.BACKUPS_DIR = orig_b
            ecu_mod.MAPS_DIR    = orig_m

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print(f"\n{BOLD}{W}{'═'*70}")
    print("  VALIDACIÓN: BACKUP AUTOMÁTICO + MAPAS DE RENDIMIENTO")
    print(f"{'═'*70}{RESET}")

    for nombre, fn in [
        ("1. BACKUP AUTOMÁTICO",          test_backup_automatico),
        ("2. MAPAS DE RENDIMIENTO",        test_mapas_rendimiento),
        ("3. ECUReader.load_performance_maps()", test_ecu_reader_performance),
        ("4. FLUJO COMPLETO RENDIMIENTO",  test_flujo_completo_rendimiento),
    ]:
        try:
            fn()
        except Exception as e:
            print(f"\n{R}ERROR FATAL en {nombre}: {e}{RESET}")
            traceback.print_exc()

    total = PASS + FAIL
    pct   = 100.0 * PASS / total if total else 0
    color = G if FAIL == 0 else (Y if pct >= 80 else R)
    print(f"\n{BOLD}{W}{'═'*70}")
    print(f"  RESULTADO: {color}{PASS}/{total} checks pasaron ({pct:.0f}%){RESET}")
    if FAIL == 0:
        print(f"{G}  Sistema 100% validado — backup + rendimiento OK{RESET}")
    else:
        print(f"{R}  {FAIL} checks fallaron{RESET}")
    print(f"{BOLD}{W}{'═'*70}{RESET}\n")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
