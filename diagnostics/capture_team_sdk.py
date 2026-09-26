"""Read one iRacing SDK frame for a side-by-side Team Session comparison.

Run once while in the session: python diagnostics/capture_team_sdk.py
The output includes other drivers' names; share only with people you trust.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def capture(ir):
    def get(key, default=None):
        try:return ir[key] if ir[key] is not None else default
        except (KeyError,TypeError,AttributeError):return default
    ir.freeze_var_buffer_latest()
    try:
        driver_info=get('DriverInfo',{}) or {}
        sessions=(get('SessionInfo',{}) or {}).get('Sessions',[])
        current=get('SessionNum',0)
        session=sessions[current] if isinstance(current,int) and 0<=current<len(sessions) else {}
        return {'capturedUTC':datetime.now(timezone.utc).isoformat(),
                'WeekendInfo':get('WeekendInfo',{}),
                'DriverInfo':{'DriverCarIdx':driver_info.get('DriverCarIdx'),
                              'DriverUserID':driver_info.get('DriverUserID'),
                              'DriverCarFuelMaxLtr':driver_info.get('DriverCarFuelMaxLtr'),
                              'Drivers':driver_info.get('Drivers',[])},
                'SessionNum':current,'ResultsPositions':session.get('ResultsPositions',[]),
                'SessionTimeRemain':get('SessionTimeRemain'),
                'PlayerCarIdx':get('PlayerCarIdx'),
                'IsOnTrack':get('IsOnTrack'),
                'FuelLevelLocal':get('FuelLevel'),
                'CarIdxLap':get('CarIdxLap',[]),
                'CarIdxLapCompleted':get('CarIdxLapCompleted',[]),
                'CarIdxLapDistPct':get('CarIdxLapDistPct',[]),
                'CarIdxOnPitRoad':get('CarIdxOnPitRoad',[]),
                'CarIdxLastLapTime':get('CarIdxLastLapTime',[])}
    finally:ir.unfreeze_var_buffer_latest()


def main():
    try:import irsdk
    except ImportError:
        print('pyirsdk no está instalado en este Python.',file=sys.stderr);return 1
    ir=irsdk.IRSDK()
    try:
        ir.startup()
        if not ir.is_initialized or not ir.is_connected:
            print('iRacing SDK no está conectado.',file=sys.stderr);return 1
        snapshot=capture(ir)
        output=Path(sys.argv[1]) if len(sys.argv)>1 else Path(f"team_sdk_snapshot_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json")
        output.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        print(f'Captura guardada: {output.resolve()}')
        return 0
    finally:
        if ir.is_initialized:ir.shutdown()


if __name__=='__main__':raise SystemExit(main())
