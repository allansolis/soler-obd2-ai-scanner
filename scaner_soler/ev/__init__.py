"""
Módulo EV — soporte para vehículos eléctricos e híbridos.

Basado en:
  - SAE J1979-2 (OBD-II para EVs)
  - ISO 14229 UDS Mode 0x22 ReadDataByIdentifier (PIDs por marca)
  - ISO 15118-2/-20 (comunicación vehículo-cargador CCS)
  - DIN 70121 (protocolo DC legacy)
  - Refs: juherr/awesome-ev-charging, uhi22/pyPLC, mobilityhouse/ocpp
"""
from scaner_soler.ev.ev_pid_registry import EV_MODE01_PIDS, EV_UDS_PIDS, EV_BRANDS, decode_ev
from scaner_soler.ev.bms_reader import BMSData, BMSReader
from scaner_soler.ev.charging_session import ChargingSession, ChargingState
from scaner_soler.ev.dtc_ev_codes import EV_DTC_DB, classify_ev_dtc, is_ev_dtc

__all__ = [
    "EV_MODE01_PIDS", "EV_UDS_PIDS", "EV_BRANDS", "decode_ev",
    "BMSData", "BMSReader",
    "ChargingSession", "ChargingState",
    "EV_DTC_DB", "classify_ev_dtc", "is_ev_dtc",
]
