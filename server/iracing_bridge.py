"""Local iRacing telemetry bridge and web server.

Serves the dashboard and broadcasts a compact timing payload over WebSocket.
Runs in demo mode automatically until iRacing's SDK is available.
"""
import argparse
import asyncio
import json
import math
import logging
from logging.handlers import RotatingFileHandler
import os
import time
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from updater import start_background_updater
except Exception:
    start_background_updater = None

try:
    from server.session_state import SessionIdentity, SessionState
    from server.lap_coach import LapCoach, number
    from server.audio_coach import AudioCoach
    from server.session_recorder import SessionRecorder
    from server.session_intelligence import build_intelligence, strategy_intelligence
    from server.race_director import RaceDirector
    from server.strategy_runtime import strategy_payload as endurance_strategy_payload,clock_text,RacePlanRuntime,leader_from_results,is_caution_flag
    from server.race_state import RaceIdentity
    from server.team_context import TeamCarContext
    from server.team_timing import relative_position,relative_window,estimated_team_fuel
    from server.spotter_control import SpotterControl
    from server.stop_plan import build_stop_plan, race_plan
    from server.setup_engineer import SetupEngineer
    from server.setup_ownership import resolve_setup_owner
    from server.setup_snapshot import snapshot_from_sdk
    from server.stint_engineering_snapshot import capture_conditions, capture_tires
    from server.kpi_library import build_kpi_library
except ModuleNotFoundError:
    from session_state import SessionIdentity, SessionState
    from lap_coach import LapCoach, number
    from audio_coach import AudioCoach
    from session_recorder import SessionRecorder
    from session_intelligence import build_intelligence, strategy_intelligence
    from race_director import RaceDirector
    from strategy_runtime import strategy_payload as endurance_strategy_payload,clock_text,RacePlanRuntime,leader_from_results,is_caution_flag
    from race_state import RaceIdentity
    from team_context import TeamCarContext
    from team_timing import relative_position,relative_window,estimated_team_fuel
    from spotter_control import SpotterControl
    from stop_plan import build_stop_plan, race_plan
    from setup_engineer import SetupEngineer
    from setup_ownership import resolve_setup_owner
    from setup_snapshot import snapshot_from_sdk
    from stint_engineering_snapshot import capture_conditions, capture_tires
    from kpi_library import build_kpi_library

from aiohttp import web
try:
    import irsdk
except ImportError:
    irsdk = None

WEB_ROOT = ROOT / "web"
try:
    APP_VERSION = str(json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"])
except Exception:
    APP_VERSION = "unknown"
logger = logging.getLogger("dashboard")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = RotatingFileHandler(ROOT / "dashboard.log", maxBytes=200_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)

def seconds(value, fallback=None):
    try:
        value = float(value)
        return value if value > 0 and math.isfinite(value) else fallback
    except (TypeError, ValueError):
        return fallback

def valid_fuel(value):
    """An SDK zero/unavailable reading must not become a team fuel reference."""
    reading=number(value)
    return reading if reading is not None and reading>0 else None

def driver_controls(get):
    """Read live in-car adjustments exposed by iRacing when available."""
    values={}
    for label,keys in {
        "BrakeBias":("dcBrakeBias","BrakeBias"),
        "TractionControl":("dcTractionControl","dcTractionControl2","TractionControl"),
    }.items():
        for key in keys:
            value=get(key)
            if value is None:
                continue
            try:
                number_value=float(value)
                if math.isfinite(number_value):
                    values[label]=number_value
                    break
            except (TypeError,ValueError):
                continue
    return values

def car_label(driver):
    return driver.get("CarScreenName") or driver.get("CarScreenNameShort") or driver.get("CarPath") or "—"

def car_brand(driver):
    name = car_label(driver).lower()
    brands = (
        ("mclaren","mclaren"),("ferrari","ferrari"),("porsche","porsche"),
        ("lamborghini","lamborghini"),("mercedes","mercedes"),("bmw","bmw"),
        ("audi","audi"),("corvette","chevrolet"),("chevrolet","chevrolet"),
        ("ford","ford"),("acura","acura"),("aston","astonmartin"),
    )
    for token, brand in brands:
        if token in name:
            return brand
    return "generic"

def driver_roster_by_car(drivers):
    """Map the current SDK roster by CarIdx, never by row order or team name.

    Spectators may carry a car index too. A conflicting pair of active driver
    names is ambiguous and must not be presented as a confirmed driver.
    """
    cars={};conflicts=set()
    for entry in drivers or []:
        if not isinstance(entry,dict) or entry.get('IsSpectator'):continue
        try:idx=int(entry.get('CarIdx'))
        except (ValueError,TypeError):continue
        if idx<0:continue
        earlier=cars.get(idx)
        if earlier and earlier.get('UserID')!=entry.get('UserID'):
            conflicts.add(idx)
        elif not earlier:cars[idx]=entry
    return cars,conflicts

def local_pilot_driver(driver_info, drivers, cars, player_idx, context=None):
    """Resolve PILOTO identity from the local SDK user, never from roster row order."""
    info=driver_info or {};entries=[d for d in (drivers or []) if isinstance(d,dict)]
    car_meta=dict((cars or {}).get(player_idx,{}) or {})
    local_user=(context.local_user_id if context is not None else None) or info.get('DriverUserID')
    local_name=context.local_driver_name if context is not None else None
    identity=None
    if local_user not in (None,0,''):
        identity=next((d for d in entries if str(d.get('UserID'))==str(local_user)),None)
    if identity is not None:
        for key in ('UserID','UserName'):
            if identity.get(key) not in (None,''):car_meta[key]=identity.get(key)
        if not car_meta.get('TeamID') and identity.get('TeamID'):car_meta['TeamID']=identity.get('TeamID')
    elif local_name:
        car_meta['UserName']=local_name
    return car_meta



def session_intelligence(get,weekend,session,cars,results,player_idx,player_class_id,lap_pct,track_surface,history=None,units=None):
    return build_intelligence(get,weekend,session,cars,results,player_idx,player_class_id,lap_pct,track_surface,history,car_label,units)


def rival_strategy_intelligence(competitors,player_lap,player_fuel,fuel_per_lap,player_pit_window=None,evidence=None):
    return strategy_intelligence(competitors,player_lap,player_fuel,fuel_per_lap,player_pit_window,evidence)


def pilot_active_indices(cars, player_idx, lap_pct=None, track_surface=None):
    """Live PILOTO boards show cars currently in-world plus the local car.

    DriverInfo is a session roster and can retain cars which are no longer
    physically present. CarIdxTrackSurface, when available, is authoritative:
    negative means not in world. Without it, require a real 0..1 lap position.
    """
    lap_pct=lap_pct or [];track_surface=track_surface or [];active={player_idx}
    for idx,driver in (cars or {}).items():
        if idx==player_idx:continue
        if driver.get('CarIsPaceCar'):continue
        surface=track_surface[idx] if idx<len(track_surface) else None
        if surface is not None:
            try:
                if int(surface)<0:continue
                active.add(idx);continue
            except (TypeError,ValueError):
                pass
        pct=lap_pct[idx] if idx<len(lap_pct) else None
        try:
            pct=float(pct)
        except (TypeError,ValueError):
            continue
        if math.isfinite(pct) and 0.0<=pct<=1.0:active.add(idx)
    return active


def official_static_gap(player_result, other_result):
    """ResultsPositions.Time has no guaranteed live-relative semantics.

    Neither independently updated lap counters nor completed-lap timing prove
    an on-track interval. Keep the official order without inventing seconds.
    """
    return None


def merge_official_neighbors(relative, standings, player_idx, gap_key):
    """Preserve dynamic track order and insert missing official class neighbors."""
    own=next((r for r in standings if r.get("idx")==player_idx),None)
    if not own:return relative
    rows=[dict(r) for r in relative]
    if not any(r.get("idx")==player_idx for r in rows):
        player=dict(own,gap="TÚ",gapSource="OFFICIAL_POSITION_ONLY")
        player[gap_key]=0.0
        rows.append(player)
    for offset in (-1,0,1):
        official=next((r for r in standings if own.get("pos") is not None and r.get("pos")==own["pos"]+offset),None)
        if not official:continue
        live=next((r for r in rows if r.get("idx")==official["idx"]),None)
        if live:
            # Official class identity/order with the existing dynamic interval.
            live.update(pos=official["pos"],classPos=official["pos"])
            continue
        fallback=dict(official,gap="ESTÁTICO · SIN INTERVALO",gapSource="OFFICIAL_POSITION_ONLY")
        fallback[gap_key]=None
        player_index=next(i for i,r in enumerate(rows) if r.get("idx")==player_idx)
        rows.insert(player_index if offset<0 else player_index+1,fallback)
    return rows


def class_results_rows(results, cars, conflicts, class_id, team_idx, last_laps, lap_text, live_positions=None):
    """Official zero-based ClassPosition from ResultsPositions, class by CarIdx."""
    rows=[]
    if class_id is None:return rows
    positioned=dict(results)
    for idx,car in cars.items():
        live=(live_positions[idx] if live_positions is not None and isinstance(idx,int) and 0<=idx<len(live_positions) else None)
        if number(live) and live>0 and positioned.get(idx,{}).get('ClassPosition') is None:
            positioned[idx]={**positioned.get(idx,{}),'ClassPosition':int(live)-1,'positionSource':'CarIdxClassPosition'}
    for idx,race in positioned.items():
        if not isinstance(idx,int) or idx<0 or not isinstance(race,dict):continue
        car=cars.get(idx,{})
        if car.get('CarClassID',race.get('CarClassID'))!=class_id:continue
        raw=race.get('ClassPosition')
        try:position=int(raw)+1 if raw is not None and int(raw)>=0 else None
        except (ValueError,TypeError):position=None
        last=last_laps[idx] if idx<len(last_laps) else None
        rows.append({'idx':idx,'pos':position,'classPos':position,'classId':class_id,
            'className':car.get('CarClassShortName') or '',
            'number':str(car.get('CarNumber',race.get('CarNumber','—'))),
            'car':car_label(car),'brand':car_brand(car),
            'driver':car.get('UserName') or '—' if idx not in conflicts else '—',
            'team':car.get('TeamName') or '—','gap':'EQUIPO' if idx==team_idx else '—',
            'gapSeconds':None,'lastLap':lap_text(last or race.get('LastTime')),
            'completedLaps':race.get('LapsComplete'),'pace':'—','isPlayer':idx==team_idx})
    rows.sort(key=lambda row:(row['pos'] is None,row['pos'] or 99999,row['idx']))
    return rows

class DashboardSource:
    def __init__(self, force_demo=False):
        self.force_demo = force_demo
        self.ir = irsdk.IRSDK() if irsdk and not force_demo else None
        self.last_connect_attempt = float("-inf")
        self.connect_retry_seconds = 0.25
        self.session_state = SessionState()
        self.last_lap_number = None
        self.lap_history = []
        self.last_fuel = None
        self.fuel_at_lap_start = None
        self.fuel_per_lap = []
        self.last_player_pct = None
        self.lap_started_at = None
        self.sector_marks = []
        self.best_sectors = [None,None,None]
        self.last_lap_summary = None
        self.demo_flash_expires = time.time()+6
        self.last_recorded_lap_time = None
        self.pending_lap = None
        self.session_key = None
        self.confirmed_session_best = None
        self.last_session_time = None
        self.personal_session_best = None
        self.personal_lap_clean = False
        self.personal_incidents = None
        self.coach = LapCoach()
        self.audio_mode = "auto"
        self.coach_session_mode = "practice"
        self.race_engineer_neighbors = {}
        self.race_engineer_car_laps = {}
        self.observed_team_history = {}
        self.competitor_presence_history = {}
        self._sdk_units=None
        self._last_session_type=None
        self.last_observed_lap_time = None
        self.race_engineer_audio = []
        self.audio_coach = AudioCoach()
        self.race_plan_audio_announced=set()
        self.race_plan_audio_state=None
        self.race_plan_audio_target=None
        self.recorder = SessionRecorder(ROOT / "session_replay.jsonl")
        self.last_strategy_log_signature=None
        self.strategy_prediction_audit={}
        self.setup_engineer = SetupEngineer(ROOT)
        self.race_plan_runtime = RacePlanRuntime(ROOT)
        self.stint_active = False
        self.race_director=RaceDirector();self.strategy_settings={"baseStintLaps":37,"extendedStintLaps":38,"pitLossSeconds":30.0,"manualRaceSeconds":36000,"averageLapSeconds":None,"consumptionLiters":None,"tankCapacityLiters":None,"driverNames":["Santiago","David","Herney"]};self.strategy_driver_assignments={};self.strategy_completed_stints=[];self.strategy_stint_start_lap=None;self.strategy_stops_completed=0;self.strategy_last_on_pit=False;self.strategy_target_total_stops=None
        self.team_car_idx=None;self.manual_team_car_idx=None;self.team_car_number=None;self.manual_team_car_number=None;self.confirmed_driver_id=None;self.confirmed_driver_name=None;self.manual_team_driver=None;self.demo_role='driver';self.active_stint_driver=None;self.local_user_id=None;self.local_driver_name=None;self.team_id=None;self.team_fuel_reference=None;self.team_fuel_reference_valid=False;self.team_fuel_reference_source=None;self.spotter_control=SpotterControl();self.team_completed_now=None;self.spotter_pre_pit_fuel=None;self.manual_stop_counted=False;self.spotter_event_error=None;self.stop_overrides={};self.kpi_last_valid={};self.current_sector_times=[];self.last_completed_sectors=[];self.sector_lap_number=None;self.debug_team_enabled=False;self.capture_status='Listo para capturar';self.sector_tracking_armed=False;self.sector_last_sample=None

    def handle_race_plan_audio(self, payload):
        """Speak meaningful Race Plan transitions once for the local driver."""
        vnext=(payload or {}).get("racePlanVNext") or {}
        plan=vnext.get("currentPlan") or vnext.get("plan") or {}
        race_state=vnext.get("raceState") or {}
        window=plan.get("window") or {}
        status=str(window.get("state") or "")
        target=window.get("target")
        identity=(vnext.get("raceIdentity") or {}).get("key") or self.session_key
        self.race_plan_audio_state=status or None
        self.race_plan_audio_target=target
        if race_state.get("on_pit_road"):
            return None
        messages={
            "WINDOW OPEN":"Ventana de boxes abierta.",
            "BOX NEXT LAP":"Box próxima vuelta.",
            "BOX THIS LAP":"Box, box.",
        }
        message=messages.get(status)
        if not message or self.coach_session_mode=="qualifying":
            return None
        key=(str(identity),target,status)
        if key in self.race_plan_audio_announced:
            return None
        self.race_plan_audio_announced.add(key)
        if len(self.race_plan_audio_announced)>48:
            self.race_plan_audio_announced=set(list(self.race_plan_audio_announced)[-32:])
        logger.info("RACE PLAN AUDIO state=%s target=%s",status,target)
        if hasattr(self.audio_coach, "say_priority"):
            self.audio_coach.say_priority(message)
        else:
            self.audio_coach.say(message)
        return status

    def race_plan_suppresses_coach_audio(self):
        return self.race_plan_audio_state in ("WINDOW OPEN","BOX NEXT LAP","BOX THIS LAP")

    def capture_sdk_once(self):
        """Save one SDK frame without starting another connection or polling loop."""
        if self.ir is None or not self.ir.is_initialized or not self.ir.is_connected:
            self.capture_status='Captura fallida: iRacing SDK no conectado'
            return None
        keys=('DriverInfo','SessionInfo','SessionNum','PlayerCarIdx','SessionTime',
              'SessionTimeRemain','FuelLevel','Lap','LapCompleted',
              'CarIdxLapDistPct','CarIdxLap','CarIdxLapCompleted','CarIdxPosition',
              'CarIdxClassPosition','CarIdxLastLapTime','CarIdxBestLapTime',
              'CarIdxOnPitRoad','CarIdxEstTime','CarIdxTrackSurface','AirTemp','TrackTemp','AirPressure','AirDensity',
              'RelativeHumidity','FogLevel','WindVel','WindDir','Skies','TrackWetness','Precipitation','WeatherDeclaredWet',
              'SessionFlags','SessionState','SessionLapsRemain','SessionLapsRemainEx','PitsOpen','Lat','Lon','YawNorth')
        try:
            self.ir.freeze_var_buffer_latest()
            try:
                snapshot={key:self.get(key) for key in keys}
            finally:
                self.ir.unfreeze_var_buffer_latest()
            session_num=snapshot['SessionNum']
            sessions=(snapshot['SessionInfo'] or {}).get('Sessions',[])
            snapshot['ResultsPositions']=(sessions[session_num].get('ResultsPositions',[])
                                          if isinstance(session_num,int) and 0<=session_num<len(sessions) else None)
            stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
            filename=f'ZRE_TEAM_CAPTURE_{stamp}.json'
            content=json.dumps(snapshot,ensure_ascii=False,indent=2)
            with (ROOT/filename).open('x',encoding='utf-8') as handle:handle.write(content+'\n')
            self.capture_status=f'Guardado: {filename} · carpeta ZRE'
            return ROOT/filename
        except (OSError,ValueError,TypeError,AttributeError,IndexError) as exc:
            logger.exception('SDK CAPTURE FAILED')
            self.capture_status=f'Captura fallida: {type(exc).__name__}'
            return None

    def sdk_units(self):
        if self._sdk_units is None:
            try:
                headers=self.ir._var_headers_dict
                self._sdk_units={name:header.unit for name,header in headers.items()} if isinstance(headers,dict) else {}
            except (AttributeError,TypeError,KeyError):self._sdk_units={}
        return self._sdk_units

    def get(self,key,default=None):
        try:
            value=self.ir[key]
            return default if value is None else value
        except (KeyError,TypeError,AttributeError):
            return default

    def sample(self,force_driver=False,force_spotter=False):
        if self.force_demo:
            self.setup_engineer.set_owner(None)
            return self.demo_payload('driver' if force_driver else 'spotter' if force_spotter else None)
        if self.connect():
            try:
                payload=self.live_payload(force_driver=force_driver,force_spotter=force_spotter)
                self.session_state.remember_payload(payload)
                return payload
            except Exception as exc:
                self.setup_engineer.set_owner(None)
                return self.disconnected_payload(f"Leyendo sesión: {exc}")
        self.setup_engineer.set_owner(None)
        return self.disconnected_payload("Esperando a iRacing SDK")

    def connect(self):
        if not self.ir:return False
        if self.ir.is_initialized and self.ir.is_connected:return True
        now=time.monotonic()
        if now-self.last_connect_attempt>=self.connect_retry_seconds:
            self.last_connect_attempt=now
            try:self.ir.startup()
            except Exception:return False
        return bool(self.ir.is_initialized and self.ir.is_connected)

    @staticmethod
    def use_spotter_payload(auto_mode,force_driver=False,force_spotter=False):
        """Choose payload route without altering TeamCarContext or SDK identity."""
        if force_spotter:
            return True
        if force_driver:
            return False
        return auto_mode == 'spotter'

    def live_payload(self,force_driver=False,force_spotter=False):
        self.ir.freeze_var_buffer_latest()
        try:
            driver_info=self.get("DriverInfo",{});drivers=driver_info.get("Drivers",[])
            session_num=int(self.get("SessionNum",0))
            sessions=self.get("SessionInfo",{}).get("Sessions",[])
            session=sessions[session_num] if 0<=session_num<len(sessions) else {}
            results={}
            for race in session.get('ResultsPositions',[]):
                if not isinstance(race,dict):continue
                try:race_idx=int(race.get('CarIdx'))
                except (ValueError,TypeError):continue
                if race_idx>=0:results[race_idx]=race
            cars,roster_conflicts=driver_roster_by_car(drivers)
            weekend=self.get("WeekendInfo",{})
            player_idx=int(self.get("PlayerCarIdx",0))
            local_lap=number(self.get('Lap'));local_fuel=number(self.get('FuelLevel'))
            local_active=bool(self.get('IsOnTrackCar') or
                              (local_lap is not None and local_lap>0 and local_fuel is not None and local_fuel>0))
            context=TeamCarContext.resolve(driver_info,player_idx,self.get("IsOnTrack"),self.team_car_idx,self.manual_team_car_idx,
                                           self.local_user_id,self.local_driver_name,self.team_id,self.manual_team_car_number,self.team_car_number,
                                           local_car_active=local_active)
            self.local_user_id=context.local_user_id;self.local_driver_name=context.local_driver_name
            resolved_owner=resolve_setup_owner(context,driver_info,player_idx).payload()
            owner_driver=next((d for d in drivers if d.get("CarIdx")==context.car_idx and not d.get("IsSpectator")),None)
            setup_location={"car":car_label(owner_driver) if owner_driver else None,
                            "track":weekend.get("TrackDisplayName") or weekend.get("TrackName"),
                            "layout":weekend.get("TrackConfigName") or "default"}
            self.setup_engineer.set_owner(resolved_owner,setup_location)
            if context.team_id is not None:self.team_id=context.team_id
            if context.car_idx is not None:
                if self.team_car_idx is not None and self.team_car_idx!=context.car_idx and self.team_car_number!=context.car_number:
                    self.confirmed_driver_id=None;self.confirmed_driver_name=None
                self.team_car_idx=context.car_idx;self.team_car_number=context.car_number
            if context.local_driving and context.current_user_id is not None:
                self.confirmed_driver_id=context.current_user_id
                self.confirmed_driver_name=context.current_driver
            elif (self.confirmed_driver_id is not None and context.local_user_id is not None
                  and str(self.confirmed_driver_id)==str(context.local_user_id)
                  and str(context.current_user_id)==str(context.local_user_id)):
                # A roster entry may remain stale after the local driver leaves.
                self.confirmed_driver_name=None
            elif (self.confirmed_driver_id is not None and context.current_user_id is not None
                  and str(context.current_user_id)!=str(self.confirmed_driver_id) and context.current_driver):
                self.confirmed_driver_id=context.current_user_id
                self.confirmed_driver_name=context.current_driver
            identity=SessionIdentity.from_sdk(weekend,session_num,context.car_idx if context.car_idx is not None else player_idx)
            session_time=self.get("SessionTime")
            if self.session_state.observe_identity(identity,ignore_car_idx=True) or (self._last_session_type is not None and self._last_session_type!=session.get("SessionType")) or (number(session_time) is not None and number(self.last_session_time) is not None and session_time<self.last_session_time-1):
                logger.info("SESSION CHANGED")
                self.finalize_setup_stint_before_reset("session-change")
                self.recorder.finish_session("session-change")
                self.reset_session_tracking()
                self.recorder.start_session(identity,{"track":weekend.get("TrackDisplayName"),"sessionType":session.get("SessionType"),
                    "sessionId":weekend.get("SessionID"),"subSessionId":weekend.get("SubSessionID"),"sessionNum":session_num,"carIdx":context.car_idx})
                self.last_strategy_log_signature=None
            self.session_key=identity;self.last_session_time=session_time;self._last_session_type=session.get("SessionType")
            if self.recorder.session_id is None:
                self.recorder.start_session(identity,{"track":weekend.get("TrackDisplayName"),"sessionType":session.get("SessionType"),
                    "sessionId":weekend.get("SessionID"),"subSessionId":weekend.get("SubSessionID"),"sessionNum":session_num,"carIdx":context.car_idx})
            if context.local_driving and context.car_idx is not None:
                if not self.strategy_settings.get('tankCapacityLiters'):
                    measured_capacity=number(driver_info.get('DriverCarFuelMaxLtr'))
                    if measured_capacity and measured_capacity>0:
                        self.strategy_settings['tankCapacityLiters']=measured_capacity
                levels=self.get('CarIdxLapCompleted',[]) or []
                reading=valid_fuel(self.get('FuelLevel'))
                if context.car_idx<len(levels) and levels[context.car_idx] is not None and levels[context.car_idx]>=0 and reading is not None:
                    self.team_fuel_reference=(reading,int(levels[context.car_idx]));self.team_fuel_reference_valid=True;self.team_fuel_reference_source='REAL LOCAL'
            # Role routing is explicit: SPOTTER manual wins, PILOTO manual forces
            # the normal local-telemetry payload, and AUTO follows TeamCarContext.
            # force_driver never changes TeamCarContext/local_driving; it only selects
            # which payload ZRE emits for this websocket frame.
            # A real team driver handoff enters SPOTTER before PILOTO's normal
            # finalize branch. Persist the outgoing verified stint once.
            if not context.local_driving and self.stint_active:
                self.finalize_setup_stint_before_reset("driver-handoff")
                self.stint_active=False
            if self.use_spotter_payload(context.auto_mode,force_driver,force_spotter):
                return self.spotter_payload(context,drivers,session,results,weekend,session_time,driver_info)
            # PILOTO is always the local SDK car. TeamCarContext may decide AUTO,
            # but it must never replace PlayerCarIdx as the driver's data source.
            pilot_idx=player_idx
            live_last=self.get("CarIdxLastLapTime",[])
            valid_bests=[seconds(r.get("FastestTime")) for r in results.values()]
            session_best=min((v for v in valid_bests if v),default=None)
            if self.confirmed_session_best is not None:
                session_best=min(session_best,self.confirmed_session_best) if session_best else self.confirmed_session_best
            player_driver=local_pilot_driver(driver_info,drivers,cars,pilot_idx,context)
            player_class_id=player_driver.get("CarClassID")
            lap_pct=self.get("CarIdxLapDistPct",[]) or []
            track_surface=self.get("CarIdxTrackSurface",[]) or []
            live_overall_pos=self.get("CarIdxPosition",[]) or []
            live_class_pos=self.get("CarIdxClassPosition",[]) or []
            active_indices=pilot_active_indices(cars,pilot_idx,lap_pct,track_surface)
            raw_player_pct=lap_pct[pilot_idx] if pilot_idx<len(lap_pct) else None
            player_pct=raw_player_pct if raw_player_pct is not None and 0<=raw_player_pct<=1 else None
            speed=seconds(self.get("Speed",0),45.0)
            track_length=self.track_metres(self.get("WeekendInfo",{}).get("TrackLength","5 km"))
            standing_rows=[];relative_candidates=[]
            for idx,driver in cars.items():
                if idx not in active_indices:continue
                shown_driver=player_driver if idx==pilot_idx else driver
                result=results.get(idx,{})
                gap=None
                valid_live_pct=(player_pct is not None and idx<len(lap_pct) and lap_pct[idx] is not None and 0<=lap_pct[idx]<=1)
                if valid_live_pct:
                    delta_laps=lap_pct[idx]-player_pct
                    while delta_laps>.5:delta_laps-=1
                    while delta_laps<-.5:delta_laps+=1
                    gap=delta_laps*track_length/max(speed,1.0)
                live_overall=live_overall_pos[idx] if idx<len(live_overall_pos) else None
                live_class=live_class_pos[idx] if idx<len(live_class_pos) else None
                try:
                    overall_pos=int(result.get("Position") or (live_overall if number(live_overall) and live_overall>0 else 0))
                except (TypeError,ValueError):
                    overall_pos=int(result.get("Position") or 0)
                class_position=result.get("ClassPosition")
                try:
                    class_pos=int(class_position)+1 if class_position is not None else (int(live_class) if number(live_class) and live_class>0 else 0)
                except (TypeError,ValueError):
                    class_pos=int(class_position)+1 if class_position is not None else overall_pos
                row={"idx":idx,"pos":overall_pos,"classPos":class_pos,"classId":shown_driver.get("CarClassID"),
                     "className":shown_driver.get("CarClassShortName") or "","number":str(shown_driver.get("CarNumber","—")),
                     "car":car_label(shown_driver),"brand":car_brand(shown_driver),"driver":shown_driver.get("UserName") or "—" if idx==pilot_idx or idx not in roster_conflicts else "—",
                     "gap":"TÚ" if idx==pilot_idx else (self.gap_text(gap) if gap is not None else "—"),
                     "gapSeconds":gap if idx!=pilot_idx else 0.0,"gapSource":"DYNAMIC_ESTIMATED",
                     "lastLap":self.lap_text(live_last[idx] if idx<len(live_last) else result.get("LastTime")),
                     "pace":self.delta_text(seconds(result.get("FastestTime")),session_best),"completedLaps":result.get("LapsComplete"),"isPlayer":idx==pilot_idx}
                standing_rows.append(row)
                if valid_live_pct:relative_candidates.append(row.copy())
            standing_rows.sort(key=lambda row:(row["pos"]==0,row["pos"]))
            overall_player=next((row for row in standing_rows if row["isPlayer"]),None)
            category_rows=class_results_rows(results,cars,roster_conflicts,player_class_id,pilot_idx,live_last,self.lap_text,live_class_pos)
            for row in category_rows:
                idx=row.get("idx")
                if row["idx"]==pilot_idx:
                    row["driver"]=player_driver.get("UserName") or "Piloto";row["car"]=car_label(player_driver);row["brand"]=car_brand(player_driver);row["number"]=str(player_driver.get("CarNumber","—"))
            player = next((row for row in category_rows if row["isPlayer"]), None)
            relative_player = next((row for row in relative_candidates if row["isPlayer"]), None)
            relative = self.relative_rows(relative_candidates, relative_player) if relative_player else []
            relative=merge_official_neighbors(relative,category_rows,pilot_idx,"gapSeconds")
            # Never replay cached driver names from a previous roster snapshot.
            weekend = self.get("WeekendInfo", {})
            lap_number = int(self.get("Lap", 0))
            last_lap = seconds(self.get("LapLastLapTime"))
            if last_lap is None and player_idx < len(live_last):
                last_lap = seconds(live_last[player_idx])
            fuel=valid_fuel(self.get("FuelLevel"))
            completed_raw = self.get("LapCompleted")
            completed_laps = int(completed_raw) if completed_raw is not None else None
            result = results.get(pilot_idx, {})
            car_completed=self.get('CarIdxLapCompleted',[]) or []
            team_completed=car_completed[pilot_idx] if pilot_idx<len(car_completed) else None
            if fuel is not None and team_completed is not None and team_completed>=0:
                self.team_fuel_reference=(fuel,int(team_completed))
                self.team_fuel_reference_valid=True;self.team_fuel_reference_source='REAL LOCAL'
            session_coach_mode=self.coach_mode_for_session(session.get("SessionType"))
            self.coach_session_mode=session_coach_mode
            self.update_sector_tracking(lap_number,self.get("LapDistPct",player_pct),last_lap)
            if completed_laps is not None:
                self.update_lap_tracking(completed_laps, player_pct, fuel, last_lap, session_best, result)
            self.update_race_engineer_audio(session_coach_mode,pilot_idx,category_rows,live_last,car_completed,results)
            self.coach.set_track_context(weekend.get("TrackName") or weekend.get("TrackDisplayName"),weekend.get("TrackConfigName"),weekend.get("TrackNumTurns"))
            if session_coach_mode in ("practice","qualifying","race_engineer"):
                self.coach.capture(self.get("LapDistPct", player_pct), session_time,
                                   self.get("Speed"), self.get("Brake"), self.get("Throttle"),
                                   on_track=bool(self.get("IsOnTrack", True)) and not self.get("OnPitRoad", False),
                                   steering=self.get("SteeringWheelAngle"), gear=self.get("Gear"),
                                   yaw_rate=self.get("YawRate"), lat_accel=self.get("LatAccel"),
                                   lat=self.get("Lat"),lon=self.get("Lon"),yaw_north=self.get("YawNorth"))
            if player:
                player["lastLap"] = self.lap_text(last_lap)
            if self.confirmed_session_best is not None:
                session_best = min(session_best, self.confirmed_session_best) if session_best else self.confirmed_session_best
            for row in standing_rows:
                row["pace"] = self.delta_text(seconds(results.get(row["idx"], {}).get("FastestTime")), session_best)
            for row in category_rows:
                row["pace"] = self.delta_text(seconds(results.get(row["idx"], {}).get("FastestTime")), session_best)
            for row in relative:
                row["pace"] = self.delta_text(seconds(results.get(row["idx"], {}).get("FastestTime")), session_best)
            best_lap = self.personal_session_best
            average_lap = self.average_lap_time(seconds(last_lap))
            stop_time, stop_lap = self.stop_estimate(fuel, lap_number, average_lap)
            on_pit_road = bool(self.get("OnPitRoad", False))
            explicit_on_track = self.get("IsOnTrack")
            on_track = bool(explicit_on_track) if explicit_on_track is not None else player_pct is not None
            in_garage = not on_track and not on_pit_road
            driving_stint = bool(session_coach_mode!="qualifying" and on_track and not on_pit_road)
            if self.stint_active and not driving_stint:
                engineering=self.coach.engineering_snapshot()
                frozen = self.coach.freeze_stint_summary()
                if frozen: logger.info("COACH STINT SUMMARY frozen priorities=%s", len(frozen))
                end_tires=capture_tires(self.get);end_conditions=capture_conditions(self.get)
                saved=self.setup_engineer.finish_stint(engineering,fuel_end=fuel,session_time=session_time,tires_end=end_tires,conditions_end=end_conditions)
                if saved: logger.info("SETUP ENGINEER STINT SAVED number=%s validLaps=%s setup=%s",saved.get("stintNumber"),saved.get("stintPerformance",{}).get("validLaps"),saved.get("setup",{}).get("fingerprint"))
            elif not self.stint_active and driving_stint:
                self.coach.start_stint()
                sdk_setup=snapshot_from_sdk(self.get("CarSetup",{}) or {},driver_info)
                setup_snapshot=self.setup_engineer.resolve_setup(sdk_setup)
                setup_session={"car":car_label(player_driver),"track":weekend.get("TrackDisplayName") or weekend.get("TrackName") or "Pista","layout":weekend.get("TrackConfigName") or "default","session":session.get("SessionType"),"driver":player_driver.get("UserName","Piloto"),"sessionID":weekend.get("SessionID"),"subSessionID":weekend.get("SubSessionID"),"trackID":weekend.get("TrackID")}
                setup_conditions=capture_conditions(self.get)
                setup_tires=capture_tires(self.get)
                setup_controls=driver_controls(self.get)
                self.setup_engineer.start_stint(setup_session,setup_snapshot,setup_conditions,fuel_start=fuel,session_time=session_time,tires_start=setup_tires,controls_start=setup_controls)
                logger.info("COACH STINT START setup=%s source=%s",setup_snapshot.get("fingerprint"),setup_snapshot.get("source"))
            if driving_stint and self.setup_engineer.current is not None:
                self.setup_engineer.observe_controls(driver_controls(self.get),session_time=session_time,lap=lap_number)
            self.stint_active = driving_stint
            completed_for_strategy=completed_laps if completed_laps is not None else max(0,lap_number-1)
            if driving_stint and self.strategy_stint_start_lap is None:self.strategy_stint_start_lap=completed_for_strategy
            if on_pit_road and not self.strategy_last_on_pit and self.strategy_stint_start_lap is not None:
                stint_laps=max(0,completed_for_strategy-self.strategy_stint_start_lap)
                if stint_laps>0:
                    previous_driver=self.strategy_completed_stints[-1].get("driver") if self.strategy_completed_stints else None;current_driver=player_driver.get("UserName","Piloto")
                    self.strategy_completed_stints.append({"number":self.strategy_stops_completed+1,"laps":stint_laps,"driver":current_driver,"double":bool(previous_driver==current_driver),"endLap":completed_for_strategy});self.strategy_stops_completed+=1
                self.strategy_stint_start_lap=None
            self.strategy_last_on_pit=on_pit_road
            self.session_state.update_runtime(session_time=session_time, connected=True, on_track=on_track, on_pit_road=on_pit_road, in_garage=in_garage)
            payload = {
                "appVersion": installed_version(),
                "connected": True, "demo": False,
                "header": {"car": car_label(player_driver), "track": weekend.get("TrackDisplayName", "Pista"),
                           "driver": player_driver.get("UserName", "Piloto"), "position": f"P{player['pos']}" if player else "P—",
                           "lap": f"VUELTA {lap_number}", "state": self.session_type_text(session.get("SessionType", "EN SESIÓN"))},
                "self": {"fuel": f"{fuel:.1f} L · REAL LOCAL" if fuel is not None else "—",
                         "fuelValue":fuel,"fuelSource":'REAL LOCAL' if fuel is not None else 'SIN DATO',
                         "lastUse": self.use_text(sum(self.fuel_per_lap) / len(self.fuel_per_lap) if self.fuel_per_lap else None),
                         "bestUse": self.use_text(min(self.fuel_per_lap) if self.fuel_per_lap else None),
                         "worstUse": self.use_text(max(self.fuel_per_lap) if self.fuel_per_lap else None),
                         "lastLap": self.lap_text(last_lap), "bestLap": self.lap_text(best_lap),
                         "laps": self.lap_rows(self.personal_session_best), "wear": self.wear(),
                         "pit": "EN BOXES" if on_pit_road else ("EN GARAGE" if in_garage else "EN PISTA"),
                         "pitWindow": stop_time, "nextStop": stop_lap},
                "lastLapSummary": self.last_lap_summary,
                "relative": relative, "standing": self.position_window(category_rows, player),
            }
            coach = self.coach.payload(self.lap_text)
            payload["capabilities"] = {"coachControls": True}
            payload["sessionMode"] = session_coach_mode
            payload["sessionType"] = session.get("SessionType")
            coach.update(source="ZRE_INFERRED",sessionIdentity=str(identity),referenceSessionType=session.get("SessionType"))
            payload["coach"] = coach
            payload["sessionIntelligence"]=session_intelligence(self.get,weekend,session,{i:({**c,'UserName':None,'identityAmbiguous':True} if i in roster_conflicts else c) for i,c in cars.items()},results,pilot_idx,player_class_id,lap_pct,track_surface,self.competitor_presence_history,self.sdk_units())
            last_setup=(self.setup_engineer.last_saved or {}).get("setup") or {}
            valid_practice=[row for row in self.lap_history
                            if row.get("valid") and isinstance(row.get("time"),(int,float)) and row["time"]>0]
            valid_fuel_laps=[row["fuelUse"] for row in valid_practice
                             if isinstance(row.get("fuelUse"),(int,float)) and 0<row["fuelUse"]<30]
            mean_pace=sum(row["time"] for row in valid_practice)/len(valid_practice) if valid_practice else None
            pace_dev=(math.sqrt(sum((row["time"]-mean_pace)**2 for row in valid_practice)/len(valid_practice))
                      if len(valid_practice)>1 else None)
            mean_fuel=sum(valid_fuel_laps)/len(valid_fuel_laps) if valid_fuel_laps else None
            previous_clean=valid_practice[-1] if valid_practice else None
            payload["practiceAnalytics"]={
                "validLaps":len(valid_practice),
                "averageLap":self.lap_text(mean_pace) if mean_pace is not None else None,
                "consistencySeconds":round(pace_dev,3) if pace_dev is not None else None,
                "lastValidLap":self.lap_text(previous_clean["time"]) if previous_clean else None,
                "lastDelta":self.delta_text(previous_clean["time"],best_lap)
                    if previous_clean and best_lap is not None else None,
                "deltaReference":"MEJOR REAL",
                "fuelLast":valid_fuel_laps[-1] if valid_fuel_laps else None,
                "fuelAverage":mean_fuel,
                "fuelMin":min(valid_fuel_laps) if valid_fuel_laps else None,
                "fuelMax":max(valid_fuel_laps) if valid_fuel_laps else None,
                "fuelLapsEstimated":round(fuel/mean_fuel,1)
                    if fuel is not None and mean_fuel is not None and mean_fuel>0 else None,
                "laps":[{"lap":row.get("lap"),"seconds":round(row["time"],3),
                         "fuelUse":row.get("fuelUse")} for row in valid_practice],
            }
            payload["setupEngineer"]={"stintActive":bool(self.setup_engineer.current),"available":bool(self.setup_engineer.last_saved),"lastStintNumber":(self.setup_engineer.last_saved or {}).get("stintNumber"),"lastSetupFingerprint":last_setup.get("fingerprint"),"setupName":(last_setup.get("metadata") or {}).get("setupName"),"setupSource":last_setup.get("source"),"driverFeedback":(self.setup_engineer.last_saved or {}).get("driverFeedback") or {},"status":self.setup_engineer.status,"reportFile":self.setup_engineer.last_report_path.name if self.setup_engineer.last_report_path else None,"owner":dict(self.setup_engineer.owner),"setupSourcePreference":self.setup_engineer.setup_source_preference,"importedSetupAvailable":bool(self.setup_engineer.imported_setup),"importedSetupFile":((self.setup_engineer.imported_setup or {}).get("metadata") or {}).get("filename")}
            payload["strategy"] = self.strategy_payload(fuel)
            payload["racePlanVNext"]=self.race_plan_vnext_payload(
                context,session,results,weekend,driver_info,player_driver.get("UserName","Piloto"),
                fuel,'REAL LOCAL' if fuel is not None else 'SIN DATO',lap_number,completed_for_strategy,
                average_lap,on_pit_road,session_time)
            intel=payload["sessionIntelligence"]
            competitors=intel["competitors"]["observed"]
            plan=payload["racePlanVNext"].get("currentPlan") or {}
            clean_laps=[r for r in self.lap_history if r.get("valid") and number(r.get("time"))]
            clean_pace=sum(r["time"] for r in clean_laps[-5:])/len(clean_laps[-5:]) if len(clean_laps)>=3 else None
            traffic=intel["traffic"]["observed"]
            traffic_clear=not any(r.get("presence")=="STALE" and r.get("sameClass") for r in competitors) and not any(r and abs(r.get("relativeLapFraction") or 0)<.03 for r in (traffic.get("nearestAhead"),traffic.get("nearestBehind")))
            payload["rivalStrategy"]=rival_strategy_intelligence(competitors,lap_number,fuel,self.fuel_per_lap,plan.get("window"),
                {"cleanPace":clean_pace,"cleanLaps":clean_laps,"planAvailable":bool(plan.get("available")),
                 "fuelSource":"REAL LOCAL" if context.local_driving and fuel is not None else "SIN DATO",
                 "caution":intel["caution"],"pitsOpen":intel["session"]["observed"].get("pitsOpen"),"trafficClear":traffic_clear}) if session_coach_mode=="race_engineer" else {"available":False,"source":"ZRE_INFERRED"}
            self.handle_race_plan_audio(payload)
            self.flush_race_engineer_audio()
            pit_flags=self.get("CarIdxOnPitRoad",[]) or [];lap_array=self.get("CarIdxLap",[]) or [];pit_by_idx={idx:bool(pit_flags[idx]) for idx in range(len(pit_flags))};lap_by_idx={idx:lap_array[idx] for idx in range(len(lap_array))}
            payload["raceDirector"]=self.race_director.payload(category_rows,pilot_idx,pit_by_idx,lap_by_idx)
            payload["enduranceStrategy"]=self.endurance_strategy_payload(fuel,lap_number,completed_for_strategy,average_lap,session_time,driver_info,player_driver.get("UserName","Piloto"))
            in_front=min((r for r in relative if r.get('gapSeconds') is not None and r['gapSeconds']>0),key=lambda r:r['gapSeconds'],default=None)
            behind=max((r for r in relative if r.get('gapSeconds') is not None and r['gapSeconds']<0),key=lambda r:r['gapSeconds'],default=None)
            payload["teamContext"]={"autoMode":"driver","carIdx":context.car_idx,"driver":context.current_driver,
                "source":context.source,"fuelSource":"telemetry","ahead":in_front['gap'] if in_front else '—',
                "behind":behind['gap'] if behind else '—',"remainingTime":clock_text(self.get('SessionTimeRemain')),
                "stintLaps":max(0,completed_for_strategy-(self.strategy_stint_start_lap if self.strategy_stint_start_lap is not None else completed_for_strategy)),
                "teamChoices":[{'idx':context.car_idx,'label':f"#{player_driver.get('CarNumber','—')} · {player_driver.get('TeamName') or player_driver.get('UserName') or '—'}"}] if context.car_idx is not None else []}
            pilot_debug=dict(self.team_diagnostics(context),FuelLevelRaw=self.get('FuelLevel'),
                FuelLevelValidated=valid_fuel(self.get('FuelLevel')),fuelValueUsed=fuel,
                fuelSource='REAL LOCAL' if fuel is not None else 'SIN DATO',
                localDriving=context.local_driving)
            if self.debug_team_enabled:pilot_debug.update(rosterConflicts=sorted(roster_conflicts),relativeRoster=[{'carIdx':r['idx'],'sdkUserName':cars.get(r['idx'],{}).get('UserName'),'shownDriver':r['driver']} for r in relative],classResultPositions=[{'carIdx':r['idx'],'classPositionRaw':results.get(r['idx'],{}).get('ClassPosition'),'shownPosition':r['pos'],'overallPosition':results.get(r['idx'],{}).get('Position')} for r in category_rows])
            payload['teamDebug']=pilot_debug
            raw_session_state = self.get("SessionState")
            try:
                ended = int(raw_session_state) in (5, 6)
            except (TypeError, ValueError):
                ended = False
            payload["sessionSummary"] = {"active": bool(ended and in_garage), "bestLap": coach["bestLap"],
                                         "optimalLap": coach["optimalLap"], "potential": coach["potential"],
                                         "lapCount": self.coach.completed, "priorities": self.coach.summary_priorities()}
            payload["strategySettings"]={"pitLossSeconds":self.strategy_settings.get("pitLossSeconds")}
            payload["coach"]["optimalSeconds"]=self.coach.optimal
            payload["kpiLibrary"]=build_kpi_library(
                self.get,payload,role="driver",car_idx=pilot_idx,car=player_driver,result=result,drivers=drivers,
                overall_rows=standing_rows,class_rows=category_rows,fuel_history=self.fuel_per_lap,
                lap_history=self.lap_history,best_sectors=self.best_sectors,completed_laps=completed_for_strategy,
                current_lap=lap_number,fuel_value=fuel,fuel_source="REAL LOCAL" if fuel is not None else "SIN DATO",
                average_lap=average_lap,stint_laps=payload["teamContext"]["stintLaps"],
                current_driver=context.current_driver or player_driver.get("UserName"),last_valid=self.kpi_last_valid)
            self.recorder.observe(payload,session_time)
            return payload
        finally:
            self.ir.unfreeze_var_buffer_latest()

    def apply_stop_override(self,event):
        try:number=int(event.get('number'))
        except (TypeError,ValueError):return 'Número de parada inválido'
        if number<=self.strategy_stops_completed or number>self.strategy_stops_completed+64:
            return 'Selecciona una parada futura'
        field=event.get('field');value=event.get('value')
        if field not in ('lap','driver','fuel','liters'):return 'Campo no válido'
        if value in ('',None,'auto'):
            self.stop_overrides.setdefault(number,{}).pop(field,None)
            if not self.stop_overrides[number]:self.stop_overrides.pop(number,None)
            return None
        if field=='lap':
            try:value=int(value)
            except (TypeError,ValueError):return 'Vuelta inválida'
            if value<=int(self.team_completed_now or 0):return 'La parada debe estar en una vuelta futura'
        elif field=='driver':
            if value not in self.strategy_settings.get('driverNames',[]):return 'Piloto fuera del equipo configurado'
        elif field=='fuel':
            if value not in ('fill','add','none'):return 'Fuel inválido'
        else:
            try:value=float(value)
            except (TypeError,ValueError):return 'Litros inválidos'
            if not 0<value<=300:return 'Litros inválidos'
        self.stop_overrides.setdefault(number,{})[field]=value
        return None

    def apply_spotter_event(self,event):
        if not isinstance(event,dict):return 'Evento inválido'
        consumption=self.strategy_settings.get('consumptionLiters') or (sum(self.fuel_per_lap[-8:])/len(self.fuel_per_lap[-8:]) if self.fuel_per_lap else None)
        completed=self.team_completed_now
        fuel=self.spotter_control.fuel_at(completed,consumption)
        if fuel is None and self.team_fuel_reference_valid and self.team_fuel_reference and completed is not None:
            fuel=estimated_team_fuel(*self.team_fuel_reference,completed,consumption)
        kind=event.get('action')
        if kind=='stop':self.spotter_pre_pit_fuel=fuel
        event_lap=completed
        if kind in ('fill','add_fuel','no_fuel') and self.spotter_control.pit_pending and self.spotter_control.last_stop_lap is not None:
            event_lap=self.spotter_control.last_stop_lap
            fuel=self.spotter_pre_pit_fuel
        error=self.spotter_control.apply(event,lap=event_lap,tank_capacity=self.strategy_settings.get('tankCapacityLiters'),projected_fuel=fuel)
        if error:
            self.spotter_event_error=error
            return error
        self.spotter_event_error=None
        kind=event['action']
        if kind in ('fill','add_fuel','no_fuel'):
            self.team_fuel_reference_valid=False
        if kind in ('driver','new_stint') and self.spotter_control.manual_driver:
            self.manual_team_driver=self.spotter_control.manual_driver
        if kind=='stop':self.manual_stop_counted=bool(self.strategy_last_on_pit)
        if kind=='new_stint' and completed is not None:
            if not self.manual_stop_counted and self.spotter_control.last_stop_lap is not None:
                self.strategy_stops_completed+=1
            self.strategy_stint_start_lap=completed
            self.active_stint_driver=self.manual_team_driver
            self.manual_stop_counted=True
        return None

    def race_plan_vnext_payload(self,context,session,results,weekend,driver_info,current_driver,
                                fuel_value,fuel_source,current_lap,completed_laps,pace,on_pit,session_time):
        car_idx=context.car_idx
        car=next((d for d in (driver_info.get('Drivers',[]) or []) if isinstance(d,dict) and d.get('CarIdx')==car_idx),{}) if car_idx is not None else {}
        identity=RaceIdentity(
            weekend.get('SessionID'),weekend.get('SubSessionID'),weekend.get('TrackID'),
            weekend.get('TrackConfigName') or 'default',context.team_id,
            context.car_number or car.get('CarNumber') or 'unknown',car.get('CarID'),
            self.get('SessionNum'),
        )
        car_laps=self.get('CarIdxLap',[]) or []
        car_last=self.get('CarIdxLastLapTime',[]) or []
        _,leader_lap,leader_pace=leader_from_results(results,car_laps,car_last)
        laps_remaining=self.get('SessionLapsRemainEx')
        if laps_remaining is None:laps_remaining=self.get('SessionLapsRemain')
        physical=number(driver_info.get('DriverCarFuelMaxLtr')) or number(self.strategy_settings.get('tankCapacityLiters'))
        max_pct=number(driver_info.get('DriverCarMaxFuelPct'))
        require_tires=bool(session.get('SessionEnforceTireCompoundChange'))
        try:
            return self.race_plan_runtime.observe_frame(
                identity=identity,session_type=session.get('SessionType'),
                remaining_seconds=self.get('SessionTimeRemain'),session_total_seconds=self.get('SessionTimeTotal'),
                current_lap=current_lap,completed_laps=completed_laps,own_pace_seconds=pace,
                leader_lap=leader_lap,leader_pace_seconds=leader_pace,laps_remaining=laps_remaining,
                current_driver=current_driver,current_fuel_liters=fuel_value,fuel_source=fuel_source,
                physical_tank_liters=physical,max_fuel_pct=max_pct,on_pit_road=bool(on_pit),
                session_flags=self.get('SessionFlags'),pit_loss_seconds=self.strategy_settings.get('pitLossSeconds',30.0),
                mandatory_stops_remaining=0,require_tire_change=require_tires,
                min_drivers=weekend.get('MinDrivers'),max_drivers=weekend.get('MaxDrivers'),
                session_time=session_time,last_lap_time=(car_last[car_idx] if car_idx is not None and car_idx<len(car_last) else None),
                auto_fuel_enabled=self.get('dpFuelAutoFillEnabled'),auto_fuel_active=self.get('dpFuelAutoFillActive'),
                pit_sv_fuel=self.get('PitSvFuel'),
            )
        except (ValueError,TypeError,OverflowError,ZeroDivisionError):
            logger.exception('RACE PLAN VNEXT FAILED carIdx=%s',car_idx)
            return {'available':False,'reason':'Error en Race Plan vNext.'}

    def team_diagnostics(self,context):
        idx=context.car_idx
        def at(key):
            values=self.get(key,[]) or []
            return values[idx] if idx is not None and idx<len(values) else None
        return {'localUserID':context.local_user_id,'localDriverName':context.local_driver_name,
                'DriverUserID':context.sdk_driver_user_id,'DriverCarIdx':context.observed_driver_car_idx,
                'PlayerCarIdx':context.local_idx,'teamCarIdx':idx,'TeamID':context.team_id,
                'currentDriver':context.current_driver,'currentDriverUserID':context.current_user_id,
                'CarIdxLap':at('CarIdxLap'),'CarIdxLapCompleted':at('CarIdxLapCompleted'),
                'CarIdxLapDistPct':at('CarIdxLapDistPct'),'CarIdxOnPitRoad':at('CarIdxOnPitRoad'),
                'FuelLevelLocal':self.get('FuelLevel'),'IsOnTrack':self.get('IsOnTrack'),
                'IsOnTrackCar':self.get('IsOnTrackCar'),'autoMode':context.auto_mode,'source':context.source}

    def spotter_payload(self,context,drivers,session,results,weekend,session_time,driver_info):
        idx=context.car_idx
        arrays={name:self.get(name,[]) or [] for name in (
            'CarIdxLap','CarIdxLapCompleted','CarIdxLapDistPct','CarIdxOnPitRoad','CarIdxLastLapTime')}
        def at(name,car_idx):
            values=arrays[name]
            return values[car_idx] if car_idx is not None and car_idx<len(values) else None
        by_idx,roster_conflicts=driver_roster_by_car(drivers)
        car=by_idx.get(idx,{}) if idx is not None else {}
        result=results.get(idx,{}) if idx is not None else {}
        lap=at('CarIdxLap',idx)
        completed=at('CarIdxLapCompleted',idx)
        if completed is None:completed=result.get('LapsComplete')
        completed=int(completed) if completed is not None and completed>=0 else None
        last_lap=seconds(at('CarIdxLastLapTime',idx)) or seconds(result.get('LastTime'))
        pace=self.strategy_settings.get('averageLapSeconds') or last_lap or seconds(result.get('FastestTime'))
        consumption=self.strategy_settings.get('consumptionLiters') or (sum(self.fuel_per_lap[-8:])/len(self.fuel_per_lap[-8:]) if self.fuel_per_lap else None)
        fuel_raw=self.get('FuelLevel')
        fuel_validated=valid_fuel(fuel_raw)
        reference_fuel=estimated_team_fuel(*self.team_fuel_reference,completed,consumption) if self.team_fuel_reference_valid and self.team_fuel_reference and completed is not None else None
        if reference_fuel is None and self.team_fuel_reference_valid and self.team_fuel_reference and completed==self.team_fuel_reference[1]:
            reference_fuel=self.team_fuel_reference[0]
        if fuel_validated is not None and idx is not None and completed is not None:
            self.team_fuel_reference=(fuel_validated,completed)
            self.team_fuel_reference_valid=True
            self.team_fuel_reference_source='REAL LOCAL' if context.local_driving else 'SDK OBSERVADO'
        pct=at('CarIdxLapDistPct',idx)
        pit=at('CarIdxOnPitRoad',idx)
        self.team_completed_now=completed
        if pit is True and not self.strategy_last_on_pit:
            self.spotter_pre_pit_fuel=self.spotter_control.fuel_at(completed,consumption)
            if self.spotter_pre_pit_fuel is None:self.spotter_pre_pit_fuel=fuel_validated if fuel_validated is not None else reference_fuel
            self.spotter_control.pit_transition(True,completed)
            self.manual_stop_counted=True
        elif pit is False and self.strategy_last_on_pit:
            self.spotter_control.pit_transition(False,completed)
        manual_fuel=self.spotter_control.fuel_at(completed,consumption)
        fuel_used=(fuel_validated if fuel_validated is not None else
                   manual_fuel if manual_fuel is not None else reference_fuel)
        fuel_source=('REAL LOCAL' if context.local_driving else 'SDK OBSERVADO') if fuel_validated is not None else 'ESTIMADO' if fuel_used is not None else 'SIN DATO'
        if idx is not None and completed is not None:
            if self.strategy_stint_start_lap is None and pit is False:
                self.strategy_stint_start_lap=completed
                self.active_stint_driver=self.manual_team_driver or self.confirmed_driver_name
            current_name=self.manual_team_driver or self.confirmed_driver_name
            if (pit is False and current_name and self.active_stint_driver
                    and current_name!=self.active_stint_driver and self.strategy_stint_start_lap is not None):
                stint_laps=max(0,completed-self.strategy_stint_start_lap)
                previous=self.strategy_completed_stints[-1].get('driver') if self.strategy_completed_stints else None
                self.strategy_completed_stints.append({'number':self.strategy_stops_completed+1,
                    'laps':stint_laps,'driver':self.active_stint_driver,
                    'double':previous==self.active_stint_driver,'endLap':completed})
                self.strategy_stops_completed+=1
                self.strategy_stint_start_lap=completed
                self.active_stint_driver=current_name
            if pit is True and not self.strategy_last_on_pit and self.strategy_stint_start_lap is not None:
                stint_laps=max(0,completed-self.strategy_stint_start_lap)
                if stint_laps:
                    previous=self.strategy_completed_stints[-1].get('driver') if self.strategy_completed_stints else None
                    driver=self.active_stint_driver or self.manual_team_driver or self.confirmed_driver_name or '—'
                    self.strategy_completed_stints.append({'number':self.strategy_stops_completed+1,
                        'laps':stint_laps,'driver':driver,'double':previous==driver,'endLap':completed})
                    self.strategy_stops_completed+=1
                self.strategy_stint_start_lap=None
                self.active_stint_driver=None
            if pit is not None:self.strategy_last_on_pit=bool(pit)
        # Session results are the authoritative roster; dynamic arrays are a separate
        # subset of cars currently positioned by the SDK.
        class_id=context.car_class_id
        class_rows=class_results_rows(results,by_idx,roster_conflicts,class_id,idx,arrays['CarIdxLastLapTime'],self.lap_text,self.get('CarIdxClassPosition',[]) or [])
        self.coach_session_mode=self.coach_mode_for_session(session.get("SessionType"))
        self.update_race_engineer_audio(self.coach_session_mode,idx,class_rows,arrays['CarIdxLastLapTime'],arrays['CarIdxLapCompleted'],results,announce_player=True)
        live=[]
        own=next((row for row in class_rows if row['isPlayer']),None)
        standing=self.position_window(class_rows,own) if own else []
        # Every candidate requires all three dynamic measurements. Never fill an
        # absent distance or lap counter from classification results.
        for other,other_car in by_idx.items():
            if other is None or other<0 or other_car.get('IsSpectator'):continue
            other_pct=at('CarIdxLapDistPct',other)
            other_lap=at('CarIdxLap',other)
            other_completed=at('CarIdxLapCompleted',other)
            if other_lap is None or other_lap<0 or other_completed is None or other_completed<0 or other_pct is None or not 0<=other_pct<=1:continue
            position_data=relative_position(completed,pct,other_completed,other_pct,pace) if other!=idx else (0.0,'EQUIPO')
            if position_data is None:continue
            gap,label=position_data
            race=results.get(other,{})
            live.append({'idx':other,'pos':(int(race['ClassPosition'])+1 if race.get('ClassPosition') is not None and other_car.get('CarClassID')==class_id else None),'classId':other_car.get('CarClassID'),
                'number':str(other_car.get('CarNumber','—')),'car':car_label(other_car),'brand':car_brand(other_car),
                'driver':(other_car.get('UserName') or '—') if other not in roster_conflicts else '—','gap':label,
                'relativeDelta':gap,'gapSource':'DYNAMIC_ESTIMATED','lastLap':self.lap_text(at('CarIdxLastLapTime',other) or race.get('LastTime')),
                'pace':'—','isPlayer':other==idx})
        relative=relative_window(live,idx) if idx is not None else []
        relative=merge_official_neighbors(relative,class_rows,idx,"relativeDelta")
        ahead=next((row for row in relative if own and row.get("pos")==own.get("pos")-1),None)
        behind=next((row for row in relative if own and row.get("pos")==own.get("pos")+1),None)
        driver=self.manual_team_driver or self.confirmed_driver_name or 'AUTO · no confirmado'
        team_choices=[{'idx':d.get('CarIdx'),'number':str(d.get('CarNumber','')),'label':f"#{d.get('CarNumber','—')} · {d.get('TeamName') or d.get('UserName') or '—'}"}
                      for d in drivers if isinstance(d,dict) and d.get('CarIdx') is not None
                      and d.get('CarIdx')>=0 and not d.get('IsSpectator')
                      and (context.team_id is None or d.get('TeamID')==context.team_id)]
        if idx is not None:
            try:
                strategy=self.endurance_strategy_payload(fuel_used,lap or 0,completed or 0,pace,session_time,
                                                         driver_info,driver,spotter=True)
            except (ValueError,TypeError,OverflowError,ZeroDivisionError):
                logger.exception('LEGACY STRATEGY FAILED carIdx=%s',idx)
                strategy={'available':False,'reason':'Error de cálculo en estrategia anterior.'}
        else:strategy={'available':False,'reason':'No se identificó el coche del equipo.'}
        strategy['fuelSource']=fuel_source
        strategy['fuelDataAvailable']=fuel_validated is not None
        remaining=number(self.get('SessionTimeRemain'))
        if remaining is not None and (remaining<=0 or remaining>=604800):remaining=None
        plan=race_plan(remaining_seconds=remaining,current_lap=completed or 0,lap_seconds=pace,
            pit_seconds=self.strategy_settings.get('pitLossSeconds',30),current_fuel=fuel_used,
            consumption=consumption,tank=self.strategy_settings.get('tankCapacityLiters'),
            stops_completed=max(self.strategy_stops_completed,len(self.spotter_control.stops)),current_driver=driver,
            driver_assignments=self.strategy_driver_assignments,overrides=self.stop_overrides,
            completed=self.spotter_control.stops,stint_start_lap=self.strategy_stint_start_lap,
            base_stint_laps=self.strategy_settings.get('baseStintLaps'),
            extended_stint_laps=self.strategy_settings.get('extendedStintLaps'))
        strategy['stopPlan']=plan
        race_plan_vnext=self.race_plan_vnext_payload(
            context,session,results,weekend,driver_info,driver,fuel_used,fuel_source,
            lap or 0,completed or 0,pace,pit,session_time)
        strategy['boxLap']=f"VUELTA {plan['stops'][0]['lap']}" if plan['stops'] else '—'
        strategy['stopsRemaining']=plan['stopsRemaining']
        strategy['autonomy']=f"{plan['autonomyLaps']} vueltas · {fuel_source}" if plan['autonomyLaps'] is not None else '—'
        pit_flags=arrays['CarIdxOnPitRoad'];lap_array=arrays['CarIdxLap']
        race_director=self.race_director.payload(class_rows,idx,
            {i:bool(flag) for i,flag in enumerate(pit_flags)},
            {i:value for i,value in enumerate(lap_array)}) if own else {'rival':'—','status':'Esperando coche del equipo.'}
        self.session_state.update_runtime(session_time=session_time,connected=True,
            on_track=bool(pct is not None and pct>=0),on_pit_road=bool(pit),in_garage=False)
        team_debug=dict(self.team_diagnostics(context),FuelLevelRaw=fuel_raw,FuelLevelValidated=fuel_validated,
            fuelValueUsed=fuel_used,fuelSource=fuel_source,localDriving=context.local_driving,
            racePlanState=plan['state'],racePlanMissing=plan['missing'],racePlanInputs={'remainingSeconds':remaining,'paceSeconds':pace,'fuelLiters':fuel_used,'consumptionLiters':consumption,'tankCapacityLiters':self.strategy_settings.get('tankCapacityLiters'),'completedLap':completed},totalDrivers=len(drivers),totalResults=len(results),carsWithLapDistPct=sum(v is not None and 0<=v<=1 for v in arrays['CarIdxLapDistPct']),carsWithLap=sum(v is not None and v>=0 for v in arrays['CarIdxLap']),carsWithCompletedLap=sum(v is not None and v>=0 for v in arrays['CarIdxLapCompleted']),classCarsInResults=len(class_rows),relativeAvailableCars=len(live),spotterPayloadReady=bool(idx is not None),relativeRows=len(relative),standingRows=len(standing),classId=class_id,lap=lap,completedLap=completed,lapDistPct=pct,onPitRoad=pit,fuelState=self.spotter_control.fuel_source,strategySource='SDK + MANUAL' if self.spotter_control.events else 'SDK + ESTIMACIÓN')
        if self.debug_team_enabled:
            team_debug.update(rosterConflicts=sorted(roster_conflicts),relativeRoster=[{'carIdx':r['idx'],'number':r['number'],'sdkUserName':by_idx.get(r['idx'],{}).get('UserName'),'sdkTeamName':by_idx.get(r['idx'],{}).get('TeamName'),'sdkUserID':by_idx.get(r['idx'],{}).get('UserID'),'shownDriver':r['driver']} for r in relative],classResultPositions=[{'carIdx':r['idx'],'classPositionRaw':results.get(r['idx'],{}).get('ClassPosition'),'shownPosition':r['pos'],'overallPosition':results.get(r['idx'],{}).get('Position'),'sdkUserName':by_idx.get(r['idx'],{}).get('UserName'),'sdkUserID':by_idx.get(r['idx'],{}).get('UserID')} for r in class_rows])
        payload={'appVersion':installed_version(),'connected':True,'demo':False,
            'teamContext':{'autoMode':'spotter','carIdx':idx,'carNumber':context.car_number,'teamID':context.team_id,'classId':class_id,'teamName':context.team_name,'driver':driver,'driverSource':'MANUAL' if self.manual_team_driver else 'SDK' if self.confirmed_driver_name else 'NO CONFIRMADO','source':context.source,'teamChoices':team_choices,
                           'fuelSource':fuel_source,'gapSource':'estimated-car-progress',
                           'ahead':ahead['gap'] if ahead else '—','behind':behind['gap'] if behind else '—',
                           'remainingTime':clock_text(self.get('SessionTimeRemain')),'completedLaps':completed,
                           'lapDistPct':pct,'onPitRoad':pit,'fuelState':fuel_source,
                           'lastStopLap':self.spotter_control.last_stop_lap,'manualEvents':self.spotter_control.events[-12:],'controlError':self.spotter_event_error,
                           'stintLaps':max(0,(completed or 0)-(self.strategy_stint_start_lap if self.strategy_stint_start_lap is not None else (completed or 0)))},
            'header':{'car':car_label(car) if car else 'COCHE DEL EQUIPO SIN IDENTIFICAR',
                      'track':weekend.get('TrackDisplayName','Pista'),'driver':driver,
                      'position':f"P{own['pos']}" if own else 'P—',
                      'lap':f'VUELTA {lap}' if lap is not None else 'VUELTA —',
                      'state':self.session_type_text(session.get('SessionType','EN SESIÓN'))},
            'self':{'fuel':f'{fuel_used:.1f} L · {fuel_source}' if fuel_validated is not None else f'≈ {fuel_used:.1f} L · ESTIMADO' if fuel_used is not None else '—',
                    'fuelValue':fuel_used,'fuelSource':fuel_source,'lastUse':f'{consumption:.2f} L/v · EST.' if consumption else '—',
                    'bestUse':'—','worstUse':'—','lastLap':self.lap_text(last_lap),
                    'bestLap':'—','laps':list(self.observed_team_history.get(idx,[])),'wear':{'FL':'—','FR':'—','RL':'—','RR':'—'},
                    'pit':'EN BOXES' if pit else 'EN PISTA' if pct is not None and pct>=0 else 'SIN DATOS',
                    'pitWindow':'—','nextStop':strategy.get('boxLap','—')},
            'lastLapSummary':None,'relative':relative,'standing':standing,'standingAll':class_rows,'relativeAvailableCars':len(live),
            'capabilities':{'coachControls':False},'coach':{},'strategy':{},
            'raceDirector':race_director,'enduranceStrategy':strategy,'racePlan':plan,'racePlanVNext':race_plan_vnext,
            'sessionSummary':{'active':False},'teamDebug':team_debug}
        payload["sessionMode"]=self.coach_session_mode
        payload["sessionType"]=session.get("SessionType")
        payload["sessionIntelligence"]=session_intelligence(self.get,weekend,session,{i:({**c,'UserName':None,'identityAmbiguous':True} if i in roster_conflicts else c) for i,c in by_idx.items()},results,idx,class_id,arrays['CarIdxLapDistPct'],self.get('CarIdxTrackSurface',[]) or [],self.competitor_presence_history,self.sdk_units())
        payload["rivalStrategy"]={"available":False,"source":"ZRE_INFERRED","reason":"Sin ritmo/combustible local validado en SPOTTER"}
        payload["strategySettings"]={"pitLossSeconds":self.strategy_settings.get("pitLossSeconds")}
        payload["kpiLibrary"]=build_kpi_library(
            self.get,payload,role="spotter",car_idx=idx,car=car,result=result,drivers=drivers,
            overall_rows=[],class_rows=class_rows,fuel_history=[],
            lap_history=list(self.observed_team_history.get(idx,[])),best_sectors=[],
            completed_laps=completed,current_lap=lap,fuel_value=fuel_used,fuel_source=fuel_source,
            average_lap=pace,stint_laps=payload["teamContext"]["stintLaps"],current_driver=driver,last_valid={})
        self.recorder.observe(payload,session_time)
        self.handle_race_plan_audio(payload)
        self.flush_race_engineer_audio()
        return payload

    def finalize_setup_stint_before_reset(self, reason="session-change"):
        """Best-effort close of an active Setup Engineer stint before session state is cleared."""
        if not self.stint_active or self.setup_engineer.current is None:
            return None
        try:
            engineering=self.coach.engineering_snapshot()
            frozen=self.coach.freeze_stint_summary()
            if frozen:
                logger.info("COACH STINT SUMMARY frozen before reset priorities=%s reason=%s",len(frozen),reason)
            saved=self.setup_engineer.finish_stint(
                engineering,
                fuel_end=self.last_fuel,
                session_time=self.last_session_time,
                tires_end={},
                conditions_end={},
            )
            if saved:
                logger.info(
                    "SETUP ENGINEER STINT RECOVERED before reset number=%s report=%s reason=%s",
                    saved.get("stintNumber"),
                    self.setup_engineer.last_report_path.name if self.setup_engineer.last_report_path else None,
                    reason,
                )
            return saved
        except Exception:
            logger.exception("SETUP ENGINEER emergency finalize failed reason=%s",reason)
            return None

    def reset_session_tracking(self):
        self.session_state.last_valid_payload=None
        self._sdk_units=None
        self.last_strategy_log_signature=None
        self.strategy_prediction_audit={}
        self.competitor_presence_history={}
        if hasattr(self.audio_coach,"clear_pending"):self.audio_coach.clear_pending()
        self.last_lap_number=None; self.lap_history=[]; self.last_fuel=None; self.fuel_at_lap_start=None
        self.fuel_per_lap=[]; self.last_player_pct=None; self.lap_started_at=None; self.sector_marks=[]
        self.best_sectors=[None,None,None]; self.last_lap_summary=None; self.last_recorded_lap_time=None
        self.pending_lap=None; self.confirmed_session_best=None; self.personal_session_best=None
        self.personal_lap_clean=False; self.personal_incidents=None; self.coach=LapCoach(); self.coach_session_mode="practice"; self.race_engineer_neighbors={}; self.race_engineer_car_laps={}; self.observed_team_history={}; self.last_observed_lap_time=None; self.race_engineer_audio=[]; self.stint_active=False; self.race_plan_runtime.detach(); self.race_plan_audio_announced=set(); self.race_plan_audio_state=None; self.race_plan_audio_target=None; self.setup_engineer.current=None; self.setup_engineer.imported_setup=None; self.setup_engineer.setup_source_preference='auto'; self.setup_engineer.status='Esperando stint'; self.race_director=RaceDirector(); self.strategy_completed_stints=[]; self.strategy_stint_start_lap=None; self.strategy_stops_completed=0; self.strategy_last_on_pit=False; self.strategy_target_total_stops=None;self.team_fuel_reference=None;self.team_fuel_reference_valid=False;self.team_fuel_reference_source=None;self.team_car_idx=None;self.team_car_number=None;self.team_id=None;self.confirmed_driver_id=None;self.confirmed_driver_name=None;self.active_stint_driver=None;self.spotter_control=SpotterControl();self.team_completed_now=None;self.spotter_pre_pit_fuel=None;self.manual_stop_counted=False;self.spotter_event_error=None;self.stop_overrides={};self.kpi_last_valid={};self.current_sector_times=[];self.last_completed_sectors=[];self.sector_lap_number=None;self.sector_tracking_armed=False;self.sector_last_sample=None

    def update_sector_tracking(self,current_lap,lap_pct,last_lap):
        """Capture official iRacing split sectors once per completed local lap.

        SplitTimeInfo defines the sector boundaries. ZRE does not invent thirds
        when iRacing does not provide exactly three sector starts.
        """
        try:
            lap=int(current_lap)
            pct=float(lap_pct)
        except (TypeError,ValueError):
            return
        if not math.isfinite(pct) or not 0<=pct<=1:return
        info=self.get("SplitTimeInfo",{}) or {}
        raw=info.get("Sectors",[]) if isinstance(info,dict) else []
        starts=[]
        for row in raw:
            if not isinstance(row,dict):continue
            value=number(row.get("SectorStartPct"))
            if value is not None and 0<=value<1:starts.append(value)
        starts=sorted(set(starts))
        if len(starts)!=3 or starts[0]!=0:
            self.current_sector_times=[];self.last_completed_sectors=[];self.sector_tracking_armed=False;self.sector_last_sample=None
            return
        lap_time=number(self.get("LapCurrentLapTime"))
        if self.sector_lap_number is None:
            self.sector_lap_number=lap
            self.sector_tracking_armed=pct==0
            self.current_sector_times=[]
            return
        if lap!=self.sector_lap_number:
            completed=seconds(last_lap)
            if lap==self.sector_lap_number+1 and self.sector_tracking_armed and completed is not None and len(self.current_sector_times)==2:
                third=completed-sum(self.current_sector_times)
                self.last_completed_sectors=[*self.current_sector_times,third] if third>0 else []
            else:self.last_completed_sectors=[]
            self.sector_lap_number=lap;self.current_sector_times=[];self.sector_tracking_armed=pct<starts[1]
        previous=self.sector_last_sample
        self.sector_last_sample=(lap,pct,lap_time)
        if previous and previous[0]==lap and (pct<previous[1] or (lap_time is not None and previous[2] is not None and lap_time<previous[2])):
            self.current_sector_times=[];self.sector_tracking_armed=False
        if not self.sector_tracking_armed or lap_time is None:return
        thresholds=starts[1:]
        if sum(pct>=x for x in thresholds)-len(self.current_sector_times)>1:
            self.current_sector_times=[];self.sector_tracking_armed=False;self.sector_last_sample=None
            return
        while len(self.current_sector_times)<2 and pct>=thresholds[len(self.current_sector_times)]:
            elapsed=lap_time-sum(self.current_sector_times)
            if elapsed<=0:return
            self.current_sector_times.append(elapsed)

    @staticmethod
    def track_metres(value):
        try:
            number=float(str(value).replace("km","").replace("mi","").strip())
            return number*(1609.344 if "mi" in str(value).lower() else 1000)
        except ValueError:return 5000
    @staticmethod
    def gap_text(gap): return f"{gap:+.3f}" if abs(gap)<99 else ("+1 VUELTA" if gap>0 else "-1 VUELTA")
    @staticmethod
    def lap_text(value):
        value=seconds(value)
        if not value:return "—"
        return f"{int(value//60)}:{value%60:06.3f}"
    @staticmethod
    def delta_text(value,reference): return f"{value-reference:+.3f}" if value and reference else "—"
    def wear(self):
        result={}
        for corner,prefix in (("FL","LF"),("FR","RF"),("RL","LR"),("RR","RR")):
            values=[seconds(self.get(f"{prefix}wear{zone}")) for zone in ("L","M","R")];values=[v for v in values if v]
            result[corner]=f"{sum(values)/len(values)*100:.0f}%" if values else "—"
        return result
    @staticmethod
    def relative_rows(rows,player):
        if not player:return rows[:7]
        ordered=sorted(rows,key=lambda row:row["gapSeconds"],reverse=True);player_index=next(i for i,row in enumerate(ordered) if row["isPlayer"])
        return ordered[max(0,player_index-3):player_index+4]
    @staticmethod
    def position_window(rows,player):
        if not player:return rows[:7]
        index=next(i for i,row in enumerate(rows) if row["isPlayer"]);return rows[max(0,index-3):index+4]
    @staticmethod
    def use_text(value):return f"{value:.2f} L/v" if value is not None else "—"
    def average_lap_time(self,fallback=None):
        valid=[entry["time"] for entry in self.lap_history if entry.get("time")];return sum(valid)/len(valid) if valid else fallback
    @staticmethod
    def duration_text(seconds_left):
        if not seconds_left or seconds_left<=0:return "—"
        total_minutes=int(seconds_left//60);hours,minutes=divmod(total_minutes,60);return f"≈ {hours} h {minutes:02d} min" if hours else f"≈ {minutes} min"
    def stop_estimate(self,fuel,current_lap,average_lap):
        average_use=sum(self.fuel_per_lap)/len(self.fuel_per_lap) if self.fuel_per_lap else None
        if not average_use or average_use<=0:return "—","—"
        laps_left=fuel/average_use;full_laps=max(0,int(laps_left));time_left=laps_left*average_lap if average_lap else None
        return self.duration_text(time_left),f"VUELTA {current_lap+full_laps}"
    @staticmethod
    def session_type_text(value):
        text=str(value).strip().lower();translations={"race":"CARRERA","practice":"PRÁCTICA","open practice":"PRÁCTICA","qualify":"CLASIFICACIÓN","qualifying":"CLASIFICACIÓN","warmup":"CALENTAMIENTO","lone qualify":"CLASIFICACIÓN"}
        return translations.get(text,str(value).upper())

    @staticmethod
    def coach_mode_for_session(value):
        text=" ".join(str(value or "").strip().lower().split())
        if "qual" in text:
            return "qualifying"
        if "race" in text:
            return "race_engineer"
        return "practice"

    def update_race_engineer_audio(self,mode,player_idx,category_rows,live_last,car_completed,results=None,announce_player=False):
        if mode!="race_engineer":
            self.race_engineer_neighbors={}
            self.race_engineer_audio=[]
        results=results or {}
        player=next((row for row in category_rows if row.get("idx")==player_idx),None)
        neighbors={}
        if player and player.get("pos") is not None:
            for label,offset in (("Delante",-1),("Detrás",1)):
                row=next((r for r in category_rows if r.get("pos")==player["pos"]+offset),None)
                if row:neighbors[row["idx"]]=label
        # Baseline every class car, rather than the two neighbor slots. A new
        # neighbor must never replay a historical lap, even after overtaking.
        for row in category_rows:
            idx=row.get("idx")
            if not isinstance(idx,int) or idx<0:continue
            result=results.get(idx,{})
            completed=car_completed[idx] if idx<len(car_completed) else None
            if not isinstance(completed,(int,float)) or completed<0:
                completed=result.get("LapsComplete")
            if not isinstance(completed,(int,float)) or completed<0:continue
            completed=int(completed)
            lap_time=seconds(live_last[idx]) if idx<len(live_last) else None
            if lap_time is not None and lap_time<=0:lap_time=None
            official=seconds(result.get("LastTime"))
            official_match=result.get("LapsComplete")==completed and official is not None and official>0
            state=self.race_engineer_car_laps.get(idx)
            if state is None or completed<state["completed"]:
                self.race_engineer_car_laps[idx]={"completed":completed,"time":lap_time,"pending":None}
                continue
            if completed>state["completed"]:
                state["pending"]=(completed,state["time"])
                state["completed"]=completed
            pending=state["pending"]
            if pending and completed==pending[0]:
                candidate=official if official_match else lap_time
                if candidate is not None and (official_match or candidate!=pending[1]):
                    state["pending"]=None
                    if idx==player_idx and announce_player:
                        history=self.observed_team_history.setdefault(idx,[])
                        if not history or history[-1]["lap"]<completed:
                            history.append({"lap":completed,"time":self.lap_text(candidate),"delta":"—","consumption":"—"})
                            del history[:-10]
                        if mode=="race_engineer":self.race_engineer_audio.append(self.lap_text(candidate))
                    elif mode=="race_engineer" and idx in neighbors:
                        self.race_engineer_audio.append(f"{neighbors[idx]}, {self.lap_text(candidate)}")
            if lap_time is not None:state["time"]=lap_time
        self.race_engineer_neighbors=neighbors

    def flush_race_engineer_audio(self):
        messages=self.race_engineer_audio
        self.race_engineer_audio=[]
        if self.coach_session_mode=="race_engineer" and messages and not self.race_plan_suppresses_coach_audio():
            self.audio_coach.say(". ".join(messages))

    def update_lap_tracking(self,lap_number,lap_pct,fuel,last_lap,session_best,result=None):
        completed=seconds(last_lap);result=result or {};incidents=self.get("PlayerCarMyIncidentCount")
        clean_now=(incidents is not None and self.get("PlayerTrackSurface")==3 and not self.get("OnPitRoad",False) and not self.get("PlayerCarTowTime",0))
        self.personal_lap_clean=(self.personal_lap_clean and clean_now and incidents==self.personal_incidents)
        if self.last_lap_number is None:
            self.confirmed_session_best=None;prior_lap=result.get("FastestLap",0)
            self.personal_session_best=seconds(result.get("FastestTime")) if 0<prior_lap<=lap_number else None
            self.personal_lap_clean=False;self.personal_incidents=incidents;self.lap_history,self.fuel_per_lap=[],[]
            self.last_lap_summary=self.pending_lap=None;self.last_lap_number=lap_number;self.last_recorded_lap_time=completed;self.last_observed_lap_time=completed;self.fuel_at_lap_start=None;return
        if lap_number<self.last_lap_number:return
        if lap_number>self.last_lap_number:
            usage=self.fuel_at_lap_start-fuel if self.fuel_at_lap_start is not None and fuel is not None else None
            self.pending_lap={"lap":lap_number,"usage":usage,"sectors":list(self.last_completed_sectors),"previousTime":self.last_observed_lap_time,"valid":self.personal_lap_clean}
            self.personal_lap_clean=clean_now;self.personal_incidents=incidents;self.fuel_at_lap_start=fuel
            self.last_lap_number=lap_number
        if self.pending_lap:
            official_time=seconds(result.get("LastTime"))
            official_match=(result.get("LapsComplete")==self.pending_lap["lap"] and official_time is not None and official_time>0)
            candidate=official_time if official_match else completed
            best_match=(self.get("LapBestLap")==self.pending_lap["lap"] and seconds(self.get("LapBestLapTime"))==candidate)
            if candidate and candidate>0 and (candidate!=self.pending_lap["previousTime"] or official_match or best_match):
                sdk_best=seconds(self.get("LapBestLapTime"))
                if self.get("LapBestLap")==self.pending_lap["lap"] and sdk_best is not None and abs(sdk_best-candidate)<.001:
                    self.pending_lap["valid"]=True
                self.finalize_lap(self.pending_lap,candidate,session_best)
                logger.info("LAP COMPLETED %s valid=%s time=%.3f",self.pending_lap["lap"],self.pending_lap["valid"],candidate)
                self.pending_lap=None
        self.last_observed_lap_time=completed

    def finalize_lap(self,pending,completed,session_best):
        self.last_recorded_lap_time=completed
        usage=pending["usage"]
        if usage and 0<usage<30:
            self.fuel_per_lap.append(usage);self.fuel_per_lap=self.fuel_per_lap[-10:]
        sectors=pending["sectors"]
        if len(sectors)==3:
            third=completed-sum(sectors[:2])
            sectors=[*sectors[:2],third] if third>0 else []
        prior_best=self.personal_session_best
        self.lap_history.append({"lap":pending["lap"],"time":completed,"sectors":sectors,"priorBest":prior_best,"fuelUse":usage,"valid":bool(pending.get("valid"))})
        self.lap_history=self.lap_history[-10:]
        for index,value in enumerate(sectors if pending.get("valid") else []):
            if self.best_sectors[index] is None or value<self.best_sectors[index]:self.best_sectors[index]=value
        self.confirmed_session_best=min(self.confirmed_session_best,completed) if self.confirmed_session_best else completed
        self.last_lap_summary={"lap":pending["lap"],"time":self.lap_text(completed),"sessionBest":self.lap_text(prior_best),"delta":self.delta_text(completed,prior_best),"expiresAt":time.time()+6}
        if pending.get("valid") and (prior_best is None or completed<prior_best):self.personal_session_best=completed
        coach_ok=self.coach.finish(completed,pending.get("valid"))
        self.recorder.write({"type":"lap","lap":pending["lap"],"valid":bool(pending.get("valid")),"coachAccepted":bool(coach_ok),"officialTime":round(completed,4),"fuelUse":round(usage,3) if usage else None,"best":self.coach.best_lap,"optimal":self.coach.optimal,"diagnostics":self.coach.last_diagnostics,"source":"SDK_OBSERVED"})
        self.race_plan_runtime.record_local_lap(
            pending["lap"],usage,bool(pending.get("valid")),completed,
            on_pit=bool(self.get("OnPitRoad",False)),caution=is_caution_flag(self.get("SessionFlags")))
        if self.coach_session_mode=="race_engineer":
            if not self.race_plan_suppresses_coach_audio():self.race_engineer_audio.append(self.lap_text(completed))
        elif self.coach_session_mode=="practice" and coach_ok:
            logger.info("COACH GENERATED lap=%s best=%s optimal=%s priorities=%s",pending["lap"],self.coach.best_lap,self.coach.optimal,len(self.coach.advice))
            if not self.race_plan_suppresses_coach_audio():
                if self.coach.advice:
                    item=self.coach.advice[0];marker_pct=item[4] if len(item)>4 else None;phase=item[5] if len(item)>5 else None;label=self.coach.location_label(item[0],marker_pct,phase);logger.info("AUDIO PLAY location=%s zone=%s phase=%s loss=%.3f",label,item[0],phase,item[1]);self.audio_coach.say(f"{label}. Perdiste {round(item[1]*10)} décimas. {item[2]}. {item[3]}")
                else:self.audio_coach.say(f"Vuelta {pending['lap']}. Sin una pérdida clara para corregir.")
        elif self.coach_session_mode=="practice":
            logger.info("COACH SKIPPED lap=%s valid=%s",pending["lap"],pending.get("valid"))
        self.last_recorded_lap_time=completed

    def strategy_payload(self,fuel):
        uses=sorted(v for v in self.fuel_per_lap[-8:] if 0<v<30)
        if not uses or fuel is None:return {}
        representative=uses[len(uses)//2];remain=number(self.get("SessionLapsRemainEx"))
        if remain is None:remain=number(self.get("SessionLapsRemain"))
        if remain is not None and (remain<0 or remain>=32767):remain=None
        if remain is None:
            seconds_left=number(self.get("SessionTimeRemain"));pace=self.average_lap_time()
            if seconds_left is not None and (seconds_left<=0 or seconds_left>=604800):seconds_left=None
            if seconds_left and pace:remain=seconds_left/pace
        needed=(remain+1)*representative if remain is not None else None
        return {"consumption":f"{representative:.2f} L/v","lapsRemaining":f"{fuel/representative:.1f}",
                "nextStop":f"VUELTA {self.last_lap_number+int(fuel/representative)}" if self.last_lap_number is not None else "—",
                "addFuel":f"{max(0,needed-fuel):.1f} L" if needed is not None else "—"}

    def apply_strategy_settings(self,values):
        if not isinstance(values,dict):return
        numeric={"baseStintLaps":int,"extendedStintLaps":int,"pitLossSeconds":float,"manualRaceSeconds":float,"averageLapSeconds":float,"consumptionLiters":float,"tankCapacityLiters":float};reset_target=False
        for key,cast in numeric.items():
            if key not in values:continue
            raw=values.get(key)
            if raw in (None,"",0,"0") and key in ("averageLapSeconds","consumptionLiters","tankCapacityLiters"):self.strategy_settings[key]=None;continue
            try:value=cast(raw)
            except (TypeError,ValueError):continue
            if key in ("baseStintLaps","extendedStintLaps"):value=max(1,value)
            elif value<0:continue
            if self.strategy_settings.get(key)!=value and key in ("baseStintLaps","extendedStintLaps","pitLossSeconds"):reset_target=True
            self.strategy_settings[key]=value
        names=values.get("driverNames")
        if isinstance(names,list):
            cleaned=[str(name).strip() for name in names if str(name).strip()]
            if cleaned:self.strategy_settings["driverNames"]=cleaned[:6]
        assignments=values.get("driverAssignments")
        if isinstance(assignments,dict):
            cleaned={}
            for key,value in assignments.items():
                try:stint=int(key)
                except (TypeError,ValueError):continue
                name=str(value).strip() if value is not None else ""
                if stint>0 and name:cleaned[stint]=name
            self.strategy_driver_assignments=cleaned
        if self.strategy_settings["extendedStintLaps"]<self.strategy_settings["baseStintLaps"]:self.strategy_settings["extendedStintLaps"]=self.strategy_settings["baseStintLaps"]
        if reset_target:self.strategy_target_total_stops=None;self.active_stint_driver=None

    def endurance_strategy_payload(self,fuel,lap_number,completed_laps,average_lap,session_time,driver_info,current_driver,spotter=False):
        settings=self.strategy_settings;remaining=number(self.get("SessionTimeRemain"))
        if remaining is not None and (remaining<=0 or remaining>=604800):remaining=None
        if remaining is None:
            manual_total=settings.get("manualRaceSeconds");current_time=number(session_time) or 0
            if manual_total:remaining=max(0.0,float(manual_total)-current_time)
        pace=settings.get("averageLapSeconds") or average_lap;uses=sorted(v for v in self.fuel_per_lap[-8:] if 0<v<30);consumption=settings.get("consumptionLiters") or (uses[len(uses)//2] if uses and not spotter else None);tank=settings.get("tankCapacityLiters")
        if tank is None and not spotter:tank=number(driver_info.get("DriverCarFuelMaxLtr"))
        stint_completed=max(0,int(completed_laps)-int(self.strategy_stint_start_lap)) if self.strategy_stint_start_lap is not None else 0
        payload,target=endurance_strategy_payload(remaining_time_seconds=remaining,average_lap_seconds=pace,pit_loss_seconds=settings.get("pitLossSeconds",30.0),current_lap=completed_laps,current_fuel_liters=fuel,consumption_liters_per_lap=consumption,tank_capacity_liters=tank,base_stint_laps=settings.get("baseStintLaps",37),extended_stint_laps=settings.get("extendedStintLaps",38),current_stint_laps_completed=stint_completed,stops_completed=self.strategy_stops_completed,target_total_stops=self.strategy_target_total_stops,driver_assignments=self.strategy_driver_assignments,completed_stints=self.strategy_completed_stints,current_driver=current_driver)
        self.strategy_target_total_stops=target
        if payload.get('available'):
            scenario=payload.get('extended') or {};objective_laps=scenario.get('stintLaps') or settings.get('extendedStintLaps',38)
            plan=build_stop_plan(remaining_seconds=remaining,current_lap=completed_laps,lap_seconds=pace,
                pit_seconds=settings.get('pitLossSeconds',30),stint_laps=objective_laps,
                current_fuel=fuel,consumption=consumption,tank=tank,stops_completed=self.strategy_stops_completed,
                current_driver=current_driver,driver_assignments=self.strategy_driver_assignments,
                overrides=self.stop_overrides)
            plan['completed']=[{'number':item.get('number'),'lap':item.get('endLap'),
                'driver':item.get('driver'),'status':'completed'} for item in self.strategy_completed_stints[-8:]]
            payload['stopPlan']=plan
            if plan['stops']:
                payload['boxLap']=f"VUELTA {plan['stops'][0]['lap']}" + (' · MANUAL' if plan['stops'][0]['manualLap'] is not None else ' · AUTO')
            payload['stopsRemaining']=plan['stopsRemaining']
            payload['lastStopAvoidable']=plan['stopsRemaining']<payload.get('base',{}).get('stops',plan['stopsRemaining'])
        payload["settings"]=dict(payload.get("settings") or {},manualRaceSeconds=settings.get("manualRaceSeconds"),averageLapSeconds=settings.get("averageLapSeconds"),consumptionLiters=settings.get("consumptionLiters"),tankCapacityLiters=settings.get("tankCapacityLiters"),driverNames=settings.get("driverNames",[]),driverAssignments={str(k):v for k,v in self.strategy_driver_assignments.items()});
        if spotter:
            payload['fuelDataAvailable']=False
            if fuel is not None:
                payload['autonomy']=str(payload.get('autonomy','—'))+' · EST.'
                payload['boxLap']=str(payload.get('boxLap','—'))+' · EST.'
            if fuel is None:
                payload['boxLap']='— · sin combustible del coche'
                payload['targetThisStint']='ESTIMACIÓN · configurar autonomía'
                payload['fuelNeeded']='—';payload['fuelMargin']='—'
            payload['fuelSource']='ESTIMADO' if fuel is not None else 'NO DISPONIBLE'
            payload['autonomy']='SIN DATO DE COMBUSTIBLE' if fuel is None else payload.get('autonomy','—')
        return payload

    def lap_rows(self,session_best):
        return [{"lap":e["lap"],"time":self.lap_text(e["time"]),"delta":self.delta_text(e["time"],e["priorBest"]),"consumption":self.use_text(e.get("fuelUse"))} for e in self.lap_history]

    def disconnected_payload(self,message):
        self.race_engineer_car_laps={}
        self.race_engineer_audio=[]
        if hasattr(self.audio_coach,"clear_pending"):self.audio_coach.clear_pending()
        self.session_state.connected=False;payload=self.session_state.preserved_payload()
        if payload is None:payload=self.demo_payload()
        payload["connected"]=False;payload["demo"]=False;payload["header"]["state"]=message.upper()
        # Keep positions for continuity, but never present an old roster name
        # as the current driver while the SDK is disconnected.
        payload['header']['driver']='—'
        for kind in ('relative','standing','standingAll'):
            for row in payload.get(kind,[]):row['driver']='—'
        if 'teamContext' in payload:payload['teamContext']['driver']='AUTO · no confirmado'
        for row in ((payload.get('sessionIntelligence') or {}).get('competitors') or {}).get('observed') or []:
            row.update(presence='STALE',lapDistPct=None,relativeLapFraction=None,gapEvidence=None,rejoinProjection=None,sdkDisconnected=True)
        payload['rivalStrategy']={'available':False,'primary':None,'source':'ZRE_INFERRED','reason':'SDK desconectado'}
        library=payload.get('kpiLibrary') or {}
        for item in library.get('items',[]):
            if item.get('available'):
                item['state']='STALE';item['semantic']='STALE'
        library['byId']={item['id']:item for item in library.get('items',[])}
        return payload

    def demo_payload(self,role=None):
        demo_role=role or self.demo_role
        rows=[(3,"Ferrari 296 GT3","Alejandro Pérez",12.125,"1:32.184","+0.000"),(4,"Lamborghini Huracán GT3 EVO","R. Bell",10.870,"1:32.223","+0.031"),(5,"Porsche 911 GT3 R","Carlos Díaz",9.092,"1:32.122","+0.105"),(6,"Corvette Z06 GT3.R","J. Martin",6.442,"1:32.271","+0.216"),(7,"BMW M4 GT3","Lucas García",3.218,"1:32.441","+0.336"),(8,"McLaren 720S GT3 EVO","SANTIAGO",0,"1:32.481","+0.217"),(9,"Mercedes-AMG GT3","James Smith",-2.317,"1:32.612","+0.496"),(10,"Porsche 911 GT3 R","Tom Jones",-7.824,"1:32.921","+0.656"),(11,"Audi R8 LMS EVO II","M. Laurent",-11.203,"1:33.004","+0.719"),(12,"Ferrari 296 GT3","D. Werner",-14.614,"1:33.075","+0.796"),(13,"BMW M4 GT3","A. Kim",-17.202,"1:33.191","+0.838"),(14,"Acura NSX GT3 EVO","N. Rossi",-20.310,"1:33.300","+0.934")]
        standing=[{"idx":pos,"pos":pos,"classPos":pos,"classId":1,"className":"GT3","number":str(10+pos),"car":car,"brand":car_brand({"CarScreenName":car}),"driver":name,"gap":"TÚ" if gap==0 else self.gap_text(gap),"gapSeconds":gap,"lastLap":last,"pace":pace,"isPlayer":gap==0} for pos,car,name,gap,last,pace in rows]
        payload={"appVersion":APP_VERSION,"connected":True,"demo":True,"sessionMode":"race_engineer","sessionType":"Race",
                "header":{"car":"McLaren 720S GT3 EVO","track":"Spa-Francorchamps","driver":"SANTIAGO","position":"P8","lap":"VUELTA 12","state":"CARRERA · DEMO"},
                "self":{"fuel":"48.2 L","lastUse":"2.89 L/v","bestUse":"2.82 L/v","worstUse":"2.97 L/v","lastLap":"1:32.481","bestLap":"1:32.401","laps":[{"lap":10,"time":"1:32.401","delta":"—","consumption":"2.82 L/v"},{"lap":11,"time":"1:32.511","delta":"+0.110","consumption":"2.97 L/v"},{"lap":12,"time":"1:32.481","delta":"+0.080","consumption":"2.89 L/v"}],"wear":{"FL":"96%","FR":"95%","RL":"97%","RR":"96%"},"pit":"EN PISTA","pitWindow":"≈ 25 min","nextStop":"VUELTA 28"},
                "lastLapSummary":{"lap":12,"time":"1:32.481","sessionBest":"1:32.401","delta":"+0.080","expiresAt":self.demo_flash_expires},
                "relative":standing[3:10],"standing":standing[3:10],"capabilities":{"coachControls":True},
                "coach":{"reference":"ÓPTIMA SESIÓN","bestLap":"1:32.401","optimalLap":"1:31.940","potential":"0.461","lapMessage":"T1: frenaste pronto. Retrasa ligeramente la frenada.","primary":{"zone":"T1 +0.31","title":"Frenada temprana","advice":"Retrasa ligeramente la frenada manteniendo la misma velocidad mínima."},"secondary":{"zone":"T7 +0.14","title":"Aceleración tardía","advice":"Prioriza la salida y vuelve al acelerador antes."},"pattern":"T1 · 6/8 vueltas","patternAdvice":"La frenada temprana se repite de forma consistente.","trackMap":{"source":"ÚLTIMO STINT · 8 VUELTAS","points":[{"x":50+36*math.cos(i*2*math.pi/72),"y":50+30*math.sin(i*2*math.pi/72),"pct":i/72} for i in range(73)],"markers":[{"rank":1,"x":73,"y":28,"loss":.31,"label":"Primera frenada","cause":"Frenada temprana"},{"rank":2,"x":28,"y":66,"loss":.14,"label":"Cuarta frenada","cause":"Aceleración tardía"}]}},
                "strategy":{"consumption":"2.89 L/v","nextStop":"VUELTA 28","addFuel":"8.0 L","lapsRemaining":"6.2"},
                "raceDirector":{"mode":"auto","selectedIdx":7,"confidence":"AUTO","rival":"#17 · Lucas García","position":"P7","gap":"+3.218","lastLap":"1:32.441","pit":"EN PISTA","lap":"V12","status":"EN PISTA · +3.218","gapBefore":"—","netGap":"+3.218","candidates":[{"idx":7,"label":"#17 · Lucas García","position":"P7"},{"idx":9,"label":"#19 · James Smith","position":"P9"}]},
                "enduranceStrategy":{"available":True,"state":"yellow","verdict":"AHORRO NECESARIO","remainingTime":"9:43:00","currentStint":"S1 / 12","currentDriver":"SANTIAGO","boxLap":"VUELTA 28","autonomy":"16 vueltas","stopsRemaining":11,"lastStopAvoidable":True,"extensionNeeded":10,"extensionAvailable":11,"targetThisStint":"16 vueltas","base":{"stintLaps":37,"stints":13,"stops":12,"lastStintLaps":9,"projectedLaps":432},"extended":{"stintLaps":38,"stints":12,"stops":11,"lastStintLaps":37,"projectedLaps":433},"timeline":[{"number":1,"laps":16,"driver":"SANTIAGO","double":False,"status":"current","endLap":28},{"number":2,"laps":38,"driver":None,"double":False,"status":"future","endLap":66}],"settings":{"baseStintLaps":37,"extendedStintLaps":38,"pitLossSeconds":30,"manualRaceSeconds":36000,"driverNames":["Santiago","David","Herney"],"driverAssignments":{}}},
                "sessionSummary":{"active":False,"bestLap":"1:32.401","optimalLap":"1:31.940","potential":"0.461","lapCount":12,"priorities":[{"zone":"T1","title":"Frenada temprana recurrente","advice":"Apareció en 6 de las últimas 8 vueltas."},{"zone":"T7","title":"Aceleración tardía","advice":"La mayor oportunidad está en volver antes al acelerador."}]}}
        payload['teamContext']={'autoMode':demo_role,'carIdx':8,'driver':'SANTIAGO' if demo_role=='driver' else 'DAVID',
                                'source':'demo','fuelSource':'telemetry' if demo_role=='driver' else 'unavailable',
                                'ahead':'+3.2 s','behind':'-2.3 s','remainingTime':'9:43:00','stintLaps':12}
        if demo_role=='spotter':
            self.team_completed_now=11
            payload['standingAll']=standing
            payload['relativeAvailableCars']=len(standing)
            payload['racePlan']=race_plan(remaining_seconds=34980,current_lap=11,lap_seconds=92,pit_seconds=30,current_fuel=self.spotter_control.fuel_at(11,self.strategy_settings.get('consumptionLiters')),consumption=self.strategy_settings.get('consumptionLiters'),tank=self.strategy_settings.get('tankCapacityLiters'),completed=self.spotter_control.stops)
            payload['enduranceStrategy']['stopPlan']=payload['racePlan']
            payload['teamContext'].update({'completedLaps':11,'lapDistPct':.4,'onPitRoad':False,
                'teamChoices':[{'idx':8,'number':'18','label':'#18 · ZRE TEAM'}],
                'lastStopLap':self.spotter_control.last_stop_lap,
                'fuelState':self.spotter_control.fuel_source,'manualEvents':self.spotter_control.events[-12:],
                'controlError':self.spotter_event_error})
            payload['header']['driver']='DAVID'
            payload['self']['fuel']='—';payload['self']['lastUse']='—';payload['self']['wear']={key:'—' for key in ('FL','FR','RL','RR')}
            payload['coach']={};payload['capabilities']={'coachControls':False};payload['lastLapSummary']=None
            payload['enduranceStrategy']['currentDriver']='DAVID'
            payload['enduranceStrategy']['autonomy']='SIN DATO DE COMBUSTIBLE'
            payload['enduranceStrategy']['fuelDataAvailable']=False
            payload['enduranceStrategy']['fuelSource']='NO DISPONIBLE'
            estimated=self.spotter_control.fuel_at(11,self.strategy_settings.get('consumptionLiters'))
            if estimated is not None:
                payload['self']['fuel']=f'≈ {estimated:.1f} L · ESTIMADO'
                payload['enduranceStrategy']['fuelSource']='MANUAL · ESTIMADO'
        # Register the full catalog even in demo/offline startup; unknown values
        # stay unavailable instead of synthesizing SDK telemetry.
        payload['kpiLibrary']=build_kpi_library(lambda key,default=None:default,payload,
            role=demo_role,car_idx=8,overall_rows=standing,class_rows=standing,
            current_driver=payload['header']['driver'])
        return payload

@web.middleware
async def no_cache_middleware(request,handler):
    response=await handler(request)
    if request.path=="/" or request.path.startswith("/static/"):
        response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"]="no-cache"
        response.headers["Expires"]="0"
    return response

def installed_version():
    try:return str(json.loads((ROOT/"version.json").read_text(encoding="utf-8"))["version"])
    except Exception:return APP_VERSION

async def close_session_journal(app):
    source=app["source"]
    source.finalize_setup_stint_before_reset("shutdown")
    await asyncio.to_thread(source.recorder.close)

async def version_status(request):
    from zre_build import identity
    return web.json_response(identity(ROOT,APP_VERSION),headers={"Cache-Control":"no-store"})
async def index(request):return web.FileResponse(WEB_ROOT/"index.html")
async def websocket(request):
    ws=web.WebSocketResponse(heartbeat=20);await ws.prepare(request);source=request.app["source"]
    role_preference='auto'
    async def receive():
        nonlocal role_preference
        async for message in ws:
            if message.type==web.WSMsgType.TEXT:
                try:
                    import json
                    setting=json.loads(message.data)
                    if not isinstance(setting,dict):continue
                    if setting.get("type")=="settings" and setting.get("key")=="audio" and setting.get("value")=="auto":source.audio_mode="auto"
                    elif setting.get("type")=="settings" and setting.get("key")=="rival":source.race_director.set_selected(setting.get("value"))
                    elif setting.get("type")=="settings" and setting.get("key")=="strategy":source.apply_strategy_settings(setting.get("value"))
                    elif setting.get("type")=="settings" and setting.get("key")=="role" and setting.get('value') in ('auto','driver','spotter'):
                        role_preference=setting['value']
                    elif setting.get('type')=='settings' and setting.get('key')=='teamDebug':source.debug_team_enabled=bool(setting.get('value'))
                    elif setting.get("type")=="settings" and setting.get("key")=="teamCar":
                        value=setting.get('value')
                        source.manual_team_car_idx=int(value) if value not in (None,'','auto') and str(value).isdigit() else None
                        source.manual_team_car_number=str(setting.get('number')) if setting.get('number') not in (None,'') and source.manual_team_car_idx is not None else None
                    elif setting.get('type')=='settings' and setting.get('key')=='teamCarNumber':
                        source.manual_team_car_number=str(setting.get('value') or '').strip() or None
                    elif setting.get('type')=='spotterEvent':
                        source.apply_spotter_event(setting)
                    elif setting.get('type')=='stopOverride':
                        source.spotter_event_error=source.apply_stop_override(setting)
                    elif setting.get("type")=="settings" and setting.get("key")=="teamDriver":
                        source.manual_team_driver=str(setting.get('value') or '').strip()[:60] or None
                    elif setting.get("type")=="settings" and setting.get("key")=="demoRole" and source.force_demo:
                        if setting.get('value') in ('driver','spotter'):source.demo_role=setting['value']
                    elif setting.get("type")=="action" and setting.get("action")=="audio_test" and source.coach_session_mode!="qualifying":source.audio_coach.say("Prueba de audio correcta. El coach está listo para hablarte al terminar una vuelta.")
                    elif setting.get('type')=='action' and setting.get('action')=='capture_sdk':source.capture_sdk_once()
                    elif setting.get('type')=='action' and setting.get('action')=='setup_feedback':
                        if source.setup_engineer.last_saved:
                            source.setup_engineer.update_feedback(source.setup_engineer.last_saved,setting.get('entry'),setting.get('mid'),setting.get('exit'),setting.get('comment'))
                        else:source.setup_engineer.status='No hay un stint guardado para asociar feedback'
                    elif setting.get('type')=='action' and setting.get('action')=='export_setup_report':
                        if not source.setup_engineer.export_report():source.setup_engineer.status='No hay un stint guardado para exportar'
                    elif setting.get('type')=='action' and setting.get('action')=='race_plan_simulate':
                        source.race_plan_runtime.simulate_stop(setting.get('lap'))
                    elif setting.get('type')=='action' and setting.get('action')=='import_setup_html':
                        source.setup_engineer.import_html_setup(setting.get('html'),setting.get('filename'))
                    elif setting.get('type')=='settings' and setting.get('key')=='setupSource':
                        source.setup_engineer.set_setup_source(setting.get('value'))
                except (ValueError,TypeError):pass
    task=asyncio.create_task(receive())
    try:
        while not ws.closed and not task.done():
            payload=source.sample(force_driver=role_preference=='driver',force_spotter=role_preference=='spotter')
            payload['captureStatus']=source.capture_status
            await ws.send_json(payload);await asyncio.sleep(.10)
    except (ConnectionResetError,ConnectionAbortedError,BrokenPipeError,asyncio.CancelledError):pass
    finally:
        task.cancel()
        try:await task
        except (asyncio.CancelledError,ConnectionResetError,OSError):pass
    return ws

def main():
    parser=argparse.ArgumentParser(description="iRacing GT3 timing dashboard");parser.add_argument("--demo",action="store_true");parser.add_argument("--port",type=int,default=8765);args=parser.parse_args()
    app=web.Application(middlewares=[no_cache_middleware]);app["source"]=DashboardSource(args.demo)
    app.on_cleanup.append(close_session_journal)
    if start_background_updater is not None:
        start_background_updater();print("ZRE Update: vigilancia automatica activa cada 2 minutos; nunca reinicia una carrera.")
    app.router.add_get("/",index);app.router.add_get("/version",version_status);app.router.add_static("/static/",WEB_ROOT);app.router.add_get("/ws",websocket)
    print(f"Dashboard ready at http://localhost:{args.port} ({'demo' if args.demo else 'iRacing SDK'})")
    web.run_app(app,host="127.0.0.1",port=args.port,print=None)

if __name__=="__main__":main()
