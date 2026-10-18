"""
Test suite — UDSClient + MockELM327Protocol
Verifica la capa de transporte UDS sobre ELM327 simulado.

Refs implementados:
  - pylessard/python-udsoncan (ISO 14229-1)
  - Ircama/ELM327-emulator    (multi-ECU, UDS, KWP2000)
  - muki01/OBD2_K-line_Reader (K-Line/KWP2000 reference)

Ejecutar:
    python -X utf8 test_uds_elm327.py
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from scaner_soler.comm.elm327_mock import (
    MockECU,
    MockELM327Protocol,
    make_standard_mock,
)
from scaner_soler.comm.uds_client import (
    UDSClient,
    UDSNegativeResponseError,
    UDSResponse,
    SVC_DIAGNOSTIC_SESSION_CONTROL,
    SVC_READ_DATA_BY_ID,
    SVC_SECURITY_ACCESS,
    SVC_TESTER_PRESENT,
    SVC_ECU_RESET,
    SVC_NEGATIVE_RESPONSE,
    SESSION_DEFAULT,
    SESSION_EXTENDED,
    DID_VIN,
    DID_ECU_PART_NO,
    DID_SW_VERSION,
    NRC_NAMES,
    _default_seed_to_key,
)

passed = 0
failed = 0
errors_list: list[str] = []


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        errors_list.append(f"  FAIL: {name}")


def header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# Suite 1: MockELM327Protocol — respuestas AT
# ─────────────────────────────────────────────────────────────────────────────
header("Suite 1 — MockELM327Protocol: comandos AT")

mock = make_standard_mock()

check("ATZ retorna identificador ELM327", "ELM327" in mock.send_command("ATZ"))
check("ATE0 retorna OK", mock.send_command("ATE0") == "OK")
check("ATH1 retorna OK", mock.send_command("ATH1") == "OK")
check("ATSH 7E0 retorna OK", mock.send_command("ATSH 7E0") == "OK")
check("ATFCSH 7E0 retorna OK", mock.send_command("ATFCSH 7E0") == "OK")
check("ATFCSD 30 00 00 retorna OK", mock.send_command("ATFCSD 30 00 00") == "OK")
check("ATFCSM 1 retorna OK", mock.send_command("ATFCSM 1") == "OK")
check("ATDP contiene CAN", "CAN" in mock.send_command("ATDP"))
check("ATRV contiene V", "V" in mock.send_command("ATRV"))
check("ATIGN retorna ON", mock.send_command("ATIGN") == "ON")
check("Comando AT desconocido retorna OK", mock.send_command("ATXXX99") == "OK")

# ─────────────────────────────────────────────────────────────────────────────
# Suite 2: MockECU — DiagnosticSessionControl y TesterPresent
# ─────────────────────────────────────────────────────────────────────────────
header("Suite 2 — MockECU: sesión y keepalive")

ecu = MockECU(tx_id=0x7E8, name="TEST")

resp = ecu.respond(bytes([0x10, 0x03]))  # extended session
check("DSC: respuesta positiva 0x50", resp is not None and resp[0] == 0x50)
check("DSC: echo del sub-function 0x03", resp is not None and resp[1] == 0x03)
check("DSC: session guardada", ecu._session == 0x03)

resp = ecu.respond(bytes([0x3E, 0x00]))  # TesterPresent
check("TesterPresent: respuesta 0x7E", resp is not None and resp[0] == 0x7E)

resp = ecu.respond(bytes([0x11, 0x01]))  # ECUReset hard
check("ECUReset: respuesta 0x51", resp is not None and resp[0] == 0x51)
check("ECUReset: echo tipo 0x01", resp is not None and resp[1] == 0x01)

resp = ecu.respond(bytes([0x11, 0x03]))  # ECUReset soft
check("ECUReset soft: tipo 0x03", resp is not None and resp[1] == 0x03)

# ─────────────────────────────────────────────────────────────────────────────
# Suite 3: MockECU — ReadDataByIdentifier
# ─────────────────────────────────────────────────────────────────────────────
header("Suite 3 — MockECU: ReadDataByIdentifier (0x22)")

ecu = MockECU(tx_id=0x7E8)
ecu.set_vin("WMWRC3C50CT123456")

resp = ecu.respond(bytes([0x22, 0xF1, 0x90]))  # VIN
check("RDBI VIN: SID positivo 0x62", resp is not None and resp[0] == 0x62)
check("RDBI VIN: DID echo F190", resp is not None and resp[1:3] == bytes([0xF1, 0x90]))
check("RDBI VIN: datos contienen VIN", resp is not None and b"WMWRC3C50CT123456" in resp)

resp = ecu.respond(bytes([0x22, 0xF1, 0x87]))  # part number
check("RDBI PartNo: SID positivo", resp is not None and resp[0] == 0x62)
check("RDBI PartNo: DID echo F187", resp is not None and resp[1:3] == bytes([0xF1, 0x87]))

resp = ecu.respond(bytes([0x22, 0xF1, 0x89]))  # SW version
check("RDBI SWVersion: tiene datos", resp is not None and len(resp) > 3)

resp = ecu.respond(bytes([0x22, 0x12, 0x34]))  # DID desconocido
check("RDBI DID desconocido: NRC 0x7F", resp is not None and resp[0] == 0x7F)
check("RDBI DID desconocido: NRC 0x31 (requestOutOfRange)", resp is not None and resp[2] == 0x31)

resp = ecu.respond(bytes([0x22]))  # sin DID
check("RDBI sin DID: NRC por longitud", resp is not None and resp[0] == 0x7F)

# ─────────────────────────────────────────────────────────────────────────────
# Suite 4: MockECU — SecurityAccess (0x27)
# ─────────────────────────────────────────────────────────────────────────────
header("Suite 4 — MockECU: SecurityAccess (0x27)")

ecu = MockECU(tx_id=0x7E8)

# Solicitar seed (nivel 1, sub=0x01)
resp = ecu.respond(bytes([0x27, 0x01]))
check("SA: respuesta positiva 0x67", resp is not None and resp[0] == 0x67)
check("SA: echo level 0x01", resp is not None and resp[1] == 0x01)
seed = resp[2:] if resp is not None else b""
check("SA: seed no vacío", len(seed) > 0)

# Calcular clave correcta (XOR 0xFF)
key = bytes([b ^ 0xFF for b in seed])
resp = ecu.respond(bytes([0x27, 0x02]) + key)
check("SA: clave correcta → 0x67", resp is not None and resp[0] == 0x67)
check("SA: nivel guardado", ecu._security_level == 1)

# Clave incorrecta
wrong_key = bytes([0xAA] * len(seed))
ecu2 = MockECU(tx_id=0x7E8)
ecu2.respond(bytes([0x27, 0x01]))  # pedir seed
resp = ecu2.respond(bytes([0x27, 0x02]) + wrong_key)
check("SA: clave incorrecta → NRC 0x35 (invalidKey)", resp is not None and resp[0] == 0x7F and resp[2] == 0x35)

# ─────────────────────────────────────────────────────────────────────────────
# Suite 5: MockECU — DTCs
# ─────────────────────────────────────────────────────────────────────────────
header("Suite 5 — MockECU: ReadDTCInformation")

ecu = MockECU(tx_id=0x7E8)
ecu.set_dtcs(["P0300", "P0301", "U0100"])

resp = ecu.respond(bytes([0x19, 0x02, 0xFF]))
check("DTC: respuesta 0x59", resp is not None and resp[0] == 0x59)
check("DTC: sub-function 0x02 echo", resp is not None and resp[1] == 0x02)
check("DTC: datos con 3 DTCs (12 bytes = 4 bytes x 3)", resp is not None and len(resp) >= 3 + 3 * 4)

# ClearDTC
resp = ecu.respond(bytes([0x14, 0xFF, 0xFF, 0xFF]))
check("ClearDTC: respuesta 0x54", resp is not None and resp[0] == 0x54)

# Servicio no soportado
resp = ecu.respond(bytes([0x99]))
check("Servicio invalido: NRC 0x7F 0x11", resp is not None and resp[0] == 0x7F and resp[2] == 0x11)

# ─────────────────────────────────────────────────────────────────────────────
# Suite 6: MockECU — respuestas personalizadas
# ─────────────────────────────────────────────────────────────────────────────
header("Suite 6 — MockECU: respuestas personalizadas y handlers")

ecu = MockECU(tx_id=0x7E8)
ecu.add_response(
    bytes([0x22, 0xAB, 0xCD]),
    bytes([0x62, 0xAB, 0xCD, 0x01, 0x02, 0x03]),
)
resp = ecu.respond(bytes([0x22, 0xAB, 0xCD]))
check("Custom response: datos correctos", resp == bytes([0x62, 0xAB, 0xCD, 0x01, 0x02, 0x03]))

ecu.add_handler(
    lambda req: len(req) >= 2 and req[0] == 0x22 and req[1] == 0xEE,
    lambda req: bytes([0x62]) + req[1:] + b"HANDLER_OK",
)
resp = ecu.respond(bytes([0x22, 0xEE, 0x11]))
check("Handler dinamico: activado", resp is not None and b"HANDLER_OK" in resp)
check("Handler dinamico: DID preservado", resp is not None and resp[1] == 0xEE)

# ─────────────────────────────────────────────────────────────────────────────
# Suite 7: MockELM327Protocol — multi-ECU routing
# ─────────────────────────────────────────────────────────────────────────────
header("Suite 7 — MockELM327Protocol: routing multi-ECU")

mock = MockELM327Protocol()
ecu_engine = MockECU(tx_id=0x7E8, name="ENGINE")
ecu_engine.set_vin("ENGINE_VIN_12345678")
ecu_trans  = MockECU(tx_id=0x7E9, name="TRANSMISSION")
ecu_trans.add_response(bytes([0x22, 0x01, 0x00]), bytes([0x62, 0x01, 0x00, 0x05]))

mock.add_ecu(ecu_engine)
mock.add_ecu(ecu_trans)
mock.connect()

# Ruta a engine (0x7E0 → 0x7E8)
mock.send_command("ATSH 7E0")
resp = mock.send_command("22 F1 90")
# Respuesta en hex: "7E8 NN 62 F1 90 ..." — positiva si contiene "62"
check("Multi-ECU: engine retorna RDBI positivo (62)", "62" in resp and "F1" in resp and "90" in resp)

# Ruta a transmission (0x7E1 → 0x7E9)
mock.send_command("ATSH 7E1")
resp = mock.send_command("22 01 00")
check("Multi-ECU: transmission responde 62 01 00", "62" in resp and "01" in resp and "00" in resp)

# ─────────────────────────────────────────────────────────────────────────────
# Suite 8: UDSClient — capa alto nivel sobre mock
# ─────────────────────────────────────────────────────────────────────────────
header("Suite 8 — UDSClient sobre MockELM327Protocol")

mock = make_standard_mock(vin="TESTVIN12345678901")
client = UDSClient(mock, tx_id=0x7E0, rx_id=0x7E8, timeout=1.0)

# open_session
resp = client.open_session(SESSION_EXTENDED)
check("UDSClient.open_session: UDSResponse positive", resp.positive)
check("UDSClient.open_session: session state actualizado", client.current_session == SESSION_EXTENDED)

# tester_present
resp = client.tester_present()
check("UDSClient.tester_present: positive", resp.positive)

# read_vin
vin = client.read_vin()
check("UDSClient.read_vin: retorna string no vacío", isinstance(vin, str) and len(vin) > 0)
check("UDSClient.read_vin: contiene TESTVIN", "TESTVIN" in vin)

# read_ecu_info
info = client.read_ecu_info()
check("UDSClient.read_ecu_info: dict con claves", isinstance(info, dict))
check("UDSClient.read_ecu_info: part_number presente", "part_number" in info)
check("UDSClient.read_ecu_info: sw_version presente", "sw_version" in info)

# ecu_reset
resp = client.ecu_reset(0x01)
check("UDSClient.ecu_reset: positive", resp.positive)

# close_session
resp = client.close_session()
check("UDSClient.close_session: positive", resp.positive)
check("UDSClient.close_session: session vuelve a DEFAULT", client.current_session == SESSION_DEFAULT)

# ─────────────────────────────────────────────────────────────────────────────
# Suite 9: UDSClient — SecurityAccess flow
# ─────────────────────────────────────────────────────────────────────────────
header("Suite 9 — UDSClient: SecurityAccess flow completo")

mock = make_standard_mock()
client = UDSClient(mock, tx_id=0x7E0, rx_id=0x7E8)
client.open_session(SESSION_EXTENDED)

success = client.security_access(level=1, seed_to_key_fn=_default_seed_to_key)
check("SecurityAccess: flow correcto retorna True", success is True)
check("SecurityAccess: nivel guardado en client", client.security_level == 1)

# Seed 0x00 → ya desbloqueado
mock2 = make_standard_mock()
ecu_unlocked = MockECU(tx_id=0x7E8)
ecu_unlocked._security_seed = b"\x00\x00\x00\x00"
mock2._ecus[0x7E8] = ecu_unlocked
client2 = UDSClient(mock2)
client2.open_session(SESSION_EXTENDED)
check("SA: seed=0 → ya desbloqueada, retorna True", client2.security_access(1))

# ─────────────────────────────────────────────────────────────────────────────
# Suite 10: UDSResponse y NRC_NAMES
# ─────────────────────────────────────────────────────────────────────────────
header("Suite 10 — UDSResponse y NRC_NAMES")

pos = UDSResponse(service_id=0x22, data=b"\xF1\x90" + b"VIN123", positive=True)
check("UDSResponse positive: repr contiene 'ok'", "ok" in repr(pos))
check("UDSResponse positive: .positive True", pos.positive)
check("UDSResponse positive: .data tiene datos", len(pos.data) > 0)

neg = UDSResponse(service_id=0x22, data=b"\x7F\x22\x31", positive=False, nrc=0x31)
check("UDSResponse negative: repr contiene NEGATIVE", "NEGATIVE" in repr(neg))
check("UDSResponse negative: .nrc_name contiene requestOutOfRange", "requestOutOfRange" in neg.nrc_name)

check("NRC_NAMES 0x10: generalReject", NRC_NAMES[0x10] == "generalReject")
check("NRC_NAMES 0x11: serviceNotSupported", NRC_NAMES[0x11] == "serviceNotSupported")
check("NRC_NAMES 0x35: invalidKey", NRC_NAMES[0x35] == "invalidKey")
check("NRC_NAMES 0x7F: serviceNotSupportedInActiveSession", NRC_NAMES[0x7F] == "serviceNotSupportedInActiveSession")
check("NRC_NAMES 0x78: requestCorrectlyReceivedResponsePending", NRC_NAMES[0x78] == "requestCorrectlyReceivedResponsePending")

# ─────────────────────────────────────────────────────────────────────────────
# Suite 11: UDSClient — write_data_by_id
# ─────────────────────────────────────────────────────────────────────────────
header("Suite 11 — UDSClient: WriteDataByIdentifier")

mock = MockELM327Protocol()
ecu = MockECU(tx_id=0x7E8)
ecu.add_response(
    bytes([0x2E, 0x01, 0x00, 0xAB, 0xCD]),
    bytes([0x6E, 0x01, 0x00]),
)
mock.add_ecu(ecu)
mock.connect()
client = UDSClient(mock, tx_id=0x7E0, rx_id=0x7E8)

resp = client.write_data_by_id(0x0100, bytes([0xAB, 0xCD]))
check("WriteDataByID: respuesta positiva", resp.positive)

# ─────────────────────────────────────────────────────────────────────────────
# Suite 12: UDSClient — RoutineControl
# ─────────────────────────────────────────────────────────────────────────────
header("Suite 12 — UDSClient: RoutineControl")

mock = make_standard_mock()
client = UDSClient(mock)
client.open_session(SESSION_EXTENDED)

resp = client.routine_control(0xFF00, sub_function=0x01)
check("RoutineControl: respuesta", resp is not None)

# ─────────────────────────────────────────────────────────────────────────────
# Suite 13: MockELM327Protocol — log de comandos
# ─────────────────────────────────────────────────────────────────────────────
header("Suite 13 — MockELM327Protocol: log de comandos")

mock = make_standard_mock()
mock.clear_log()
mock.send_command("ATZ")
mock.send_command("ATSH 7E0")
mock.send_command("22 F1 90")
log = mock.command_log

check("Log: tiene entradas", len(log) > 0)
check("Log: ATZ registrado como >>", any("ATZ" in e and ">>" in e for e in log))
check("Log: respuesta ELM327 registrada como <<", any("ELM327" in e and "<<" in e for e in log))
check("Log: RDBI registrado", any("22" in e and "F1" in e for e in log))

mock.clear_log()
check("clear_log: log vacío", len(mock.command_log) == 0)

# ─────────────────────────────────────────────────────────────────────────────
# Suite 14: make_standard_mock
# ─────────────────────────────────────────────────────────────────────────────
header("Suite 14 — make_standard_mock helper")

m = make_standard_mock()
check("make_standard_mock: is_connected True", m.is_connected)
check("make_standard_mock: port=MOCK", m.port == "MOCK")
check("make_standard_mock: ECU 0x7E8 registrada", 0x7E8 in m._ecus)

m2 = make_standard_mock(vin="CUSTOM_VIN_ONLY_17", dtcs=["P0300", "B0001"])
check("make_standard_mock with VIN: ECU configurada", 0x7E8 in m2._ecus)
check("make_standard_mock with DTCs: DTCs en ECU", len(m2._ecus[0x7E8]._dtcs) == 2)

# ─────────────────────────────────────────────────────────────────────────────
# Resumen final
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'=' * 60}")
total = passed + failed
print(f"  RESULTADO: {passed}/{total} checks pasaron")
print("=" * 60)

if errors_list:
    print("\nFALLOS:")
    for e in errors_list:
        print(e)
    sys.exit(1)
else:
    print("\nTodos los checks pasaron.")
    sys.exit(0)
