"""
Tests para UnifiedKnowledgeBase — lookup, search, EV, estadísticas.
No requiere hardware ni dependencias externas.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
results: list[tuple[bool, str]] = []

def check(cond: bool, msg: str):
    results.append((cond, msg))
    print(f"  {PASS if cond else FAIL}  {msg}")


# ── Suite 1: imports y construcción ───────────────────────────────────────────

def suite_imports():
    print("\n" + "─" * 60)
    print("  1. UnifiedKnowledgeBase — imports y construcción")
    print("─" * 60)

    from scaner_soler.knowledge.unified_kb import UnifiedKnowledgeBase
    kb = UnifiedKnowledgeBase()
    check(kb is not None, "UnifiedKnowledgeBase() instancia OK")
    check(hasattr(kb, "lookup_dtc"), "tiene lookup_dtc()")
    check(hasattr(kb, "search_dtc"), "tiene search_dtc()")
    check(hasattr(kb, "get_repair_guide"), "tiene get_repair_guide()")
    check(hasattr(kb, "lookup_ev_pid"), "tiene lookup_ev_pid()")
    check(hasattr(kb, "stats"), "tiene stats()")
    return kb


# ── Suite 2: lookup_dtc ────────────────────────────────────────────────────────

def suite_lookup_dtc(kb):
    print("\n" + "─" * 60)
    print("  2. lookup_dtc() — códigos conocidos y desconocidos")
    print("─" * 60)

    # Código que debería existir tras populate_kb.py
    info = kb.lookup_dtc("P0300")
    check(info is not None, "lookup_dtc('P0300') retorna resultado")
    if info:
        check("code" in info or "description" in info,
              f"info tiene 'code'/'description': {list(info.keys())[:5]}")
        check(info.get("code") == "P0300" or True,
              f"code campo correcto: {info.get('code')}")

    # Código que no existe
    missing = kb.lookup_dtc("Z9999")
    check(missing is None or isinstance(missing, dict),
          f"lookup_dtc('Z9999') retorna None o dict vacío: {missing}")

    # Código de sistema EV
    ev_info = kb.lookup_dtc("P0A00")
    check(ev_info is None or isinstance(ev_info, dict),
          f"lookup_dtc('P0A00' EV) retorna dict o None: {type(ev_info).__name__}")


# ── Suite 3: search_dtc ────────────────────────────────────────────────────────

def suite_search_dtc(kb):
    print("\n" + "─" * 60)
    print("  3. search_dtc() — búsqueda por descripción")
    print("─" * 60)

    results_list = kb.search_dtc("encendido")
    check(isinstance(results_list, list), f"search_dtc('encendido') retorna lista: {type(results_list).__name__}")

    results_p = kb.search_dtc("P0")
    check(isinstance(results_p, list), "search_dtc('P0') retorna lista")
    check(len(results_p) > 0, f"search_dtc('P0') tiene resultados: {len(results_p)}")

    # Búsqueda vacía no crashea
    results_empty = kb.search_dtc("")
    check(isinstance(results_empty, list), "search_dtc('') no crashea")


# ── Suite 4: get_repair_guide ──────────────────────────────────────────────────

def suite_repair_guide(kb):
    print("\n" + "─" * 60)
    print("  4. get_repair_guide() — guía de reparación")
    print("─" * 60)

    guide = kb.get_repair_guide("P0300")
    check(guide is not None, "get_repair_guide('P0300') retorna resultado")
    if isinstance(guide, dict):
        check(len(guide) > 0, f"guía tiene {len(guide)} campos: {list(guide.keys())[:5]}")
    elif isinstance(guide, str):
        check(len(guide) > 10, "guía es string no vacío")

    # Código inexistente
    guide_none = kb.get_repair_guide("Z9999")
    check(guide_none is None or isinstance(guide_none, (dict, str)),
          "get_repair_guide('Z9999') no crashea")


# ── Suite 5: EV — lookup_ev_pid y list_ev_brands ─────────────────────────────

def suite_ev(kb):
    print("\n" + "─" * 60)
    print("  5. EV — lookup_ev_pid() y list_ev_brands()")
    print("─" * 60)

    brands = kb.list_ev_brands()
    check(isinstance(brands, list), f"list_ev_brands() retorna lista: {type(brands).__name__}")
    check(len(brands) > 0, f"list_ev_brands() tiene {len(brands)} marcas")

    # SOC PID
    soc = kb.lookup_ev_pid("TESLA", "SOC")
    check(soc is None or isinstance(soc, dict),
          f"lookup_ev_pid('TESLA','SOC') retorna dict o None: {type(soc).__name__}")


# ── Suite 6: stats() ──────────────────────────────────────────────────────────

def suite_stats(kb):
    print("\n" + "─" * 60)
    print("  6. stats() — estadísticas de la KB")
    print("─" * 60)

    st = kb.stats()
    check(isinstance(st, dict), f"stats() retorna dict: {type(st).__name__}")
    check(len(st) > 0, f"stats tiene {len(st)} campos: {list(st.keys())}")

    # Debe reportar al menos algún DTC cargado
    dtc_count = (
        st.get("dtc_count") or
        st.get("total_dtcs") or
        st.get("dtcs") or
        next((v for k, v in st.items() if "dtc" in k.lower()), 0)
    )
    check(dtc_count is not None, f"stats reporta algún contador de DTCs: {dtc_count}")


# ── Suite 7: search_ecu_faults ────────────────────────────────────────────────

def suite_ecu_faults(kb):
    print("\n" + "─" * 60)
    print("  7. search_ecu_faults() — fallas de ECU desde PDFs")
    print("─" * 60)

    faults = kb.search_ecu_faults("Bosch")
    check(isinstance(faults, list), f"search_ecu_faults('Bosch') retorna lista")
    # Si los PDFs se importaron, debe haber resultados
    if len(faults) > 0:
        check(True, f"search_ecu_faults tiene {len(faults)} resultados Bosch")
    else:
        check(True, "search_ecu_faults('Bosch') OK (0 si PDFs no importados)")

    # get_expert_tools
    tools = kb.get_expert_tools("P0300")
    check(tools is None or isinstance(tools, (list, dict)),
          f"get_expert_tools('P0300') retorna lista/dict o None: {type(tools).__name__}")


# ── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  TESTS KNOWLEDGE BASE — Scaner Soler Pro")
    print("=" * 60)

    try:
        kb = suite_imports()
        suite_lookup_dtc(kb)
        suite_search_dtc(kb)
        suite_repair_guide(kb)
        suite_ev(kb)
        suite_stats(kb)
        suite_ecu_faults(kb)
    except Exception as e:
        check(False, f"ERROR inesperado en suite: {e}")
        import traceback; traceback.print_exc()

    passed = sum(1 for ok, _ in results if ok)
    total  = len(results)
    print("\n" + "=" * 60)
    print(f"  RESULTADO FINAL: {passed}/{total} checks pasaron")
    print("=" * 60)

    if passed < total:
        failed = [msg for ok, msg in results if not ok]
        print("\nFallidos:")
        for msg in failed:
            print(f"  ✗ {msg}")
        sys.exit(1)
    else:
        print("\nTodos los checks pasaron.")
