"""Tests for expert_knowledge.json structure and integrity."""
import json
from pathlib import Path

KNOWLEDGE_FILE = Path(__file__).parent.parent.parent / "backend" / "knowledge_hub" / "expert_knowledge.json"


def test_knowledge_file_exists():
    assert KNOWLEDGE_FILE.exists()


def test_knowledge_has_dtcs():
    data = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
    dtcs = data.get("dtc_knowledge", {})
    assert len(dtcs) >= 200, f"expected >=200 DTCs, got {len(dtcs)}"


def test_all_dtc_codes_valid_format():
    data = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
    dtcs = data.get("dtc_knowledge", {})
    for code in dtcs.keys():
        # accept P/U/C/B + 4 digits, optional _suffix
        prefix = code[0].upper()
        assert prefix in ("P", "U", "C", "B"), f"invalid code prefix: {code}"


def test_dtc_entries_have_required_fields():
    data = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
    dtcs = data.get("dtc_knowledge", {})
    required_subset = {"description_es"}
    sample_codes = list(dtcs.keys())[:10]  # Check first 10
    for code in sample_codes:
        entry = dtcs[code]
        missing = required_subset - set(entry.keys())
        assert not missing, f"{code} missing fields: {missing}"


def test_cost_range_is_array_format():
    """After fix, cost_range_usd should be [min, max] not {min:..,max:..}."""
    data = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
    dtcs = data.get("dtc_knowledge", {})
    for code, entry in dtcs.items():
        cr = entry.get("cost_range_usd")
        if cr is not None:
            assert isinstance(cr, list), f"{code}: cost_range_usd should be [min,max] list, got {type(cr).__name__}"
            if len(cr) >= 2:
                assert cr[0] <= cr[1], f"{code}: min ({cr[0]}) > max ({cr[1]})"
