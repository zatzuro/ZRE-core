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
    from server.race_director import RaceDirector
    from server.strategy_runtime import strategy_payload as endurance_strategy_payload,clock_text
    from server.team_context import TeamCarContext
    from server.team_timing import relative_position,estimated_team_fuel
    from server.spotter_control import SpotterControl
except ModuleNotFoundError:
    from session_state import SessionIdentity, SessionState
    from lap_coach import LapCoach, number
    from audio_coach import AudioCoach
    from session_recorder import SessionRecorder
    from race_director import RaceDirector
    from strategy_runtime import strategy_payload as endurance_strategy_payload,clock_text
    from team_context import TeamCarContext
    from team_timing import relative_position,estimated_team_fuel
    from spotter_control import SpotterControl

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
        self.audio_mode = "off"
        self.audio_coach = AudioCoach()
        self.recorder = SessionRecorder(ROOT / "session_replay.jsonl")
        self.stint_active = False
        self.race_director=RaceDirector();self.strategy_settings={"baseStintLaps":37,"extendedStintLaps":38,"pitLossSeconds":30.0,"manualRaceSeconds":36000,"averageLapSeconds":None,"consumptionLiters":None,"tankCapacityLiters":None,"driverNames":["Santiago","David","Herney"]};self.strategy_driver_assignments={};self.strategy_completed_stints=[];self.strategy_stint_start_lap=None;self.strategy_stops_completed=0;self.strategy_last_on_pit=False;self.strategy_target_total_stops=None
        self.team_car_idx=None;self.manual_team_car_idx=None;self.manual_team_driver=None;self.demo_role='driver';self.active_stint_driver=None;self.local_user_id=None;self.local_driver_name=None;self.team_id=None;self.team_fuel_reference=None;self.team_fuel_reference_valid=False;self.spotter_control=SpotterControl();self.team_completed_now=None;self.spotter_pre_pit_fuel=None;self.manual_stop_counted=False;self.spotter_event_error=None

    def get(self,key,default=None):
        try:
            value=self.ir[key]
            return default if value is None else value
        except (KeyError,TypeError,AttributeError):
            return default

    def sample(self,force_spotter=False):
        if self.force_demo:
            return self.demo_payload()
        if self.connect():
            try:
                payload=self.live_payload(force_spotter=force_spotter)
                self.session_state.remember_payload(payload)
                return payload
            except Exception as exc:
                return self.disconnected_payload(f"Leyendo sesión: {exc}")
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

    def live_payload(self,force_spotter=False):
        self.ir.freeze_var_buffer_latest()
        try:
            driver_info=self.get("DriverInfo",{});drivers=driver_info.get("Drivers",[])
            session_num=int(self.get("SessionNum",0))
            sessions=self.get("SessionInfo",{}).get("Sessions",[])
            session=sessions[session_num] if 0<=session_num<len(sessions) else {}
            results={r.get("CarIdx"):r for r in session.get("ResultsPositions",[])}
            weekend=self.get("WeekendInfo",{})
            player_idx=int(self.get("PlayerCarIdx",0))
            context=TeamCarContext.resolve(driver_info,player_idx,self.get("IsOnTrack"),self.team_car_idx,self.manual_team_car_idx,
                                           self.local_user_id,self.local_driver_name,self.team_id)
            self.local_user_id=context.local_user_id;self.local_driver_name=context.local_driver_name
            if context.team_id is not None:self.team_id=context.team_id
            if context.car_idx is not None:self.team_car_idx=context.car_idx
            identity=SessionIdentity.from_sdk(weekend,session_num,context.car_idx if context.car_idx is not None else player_idx)
            session_time=self.get("SessionTime")
            if self.session_state.observe_identity(identity):
                logger.info("SESSION CHANGED");self.reset_session_tracking()
            self.session_key=identity;self.last_session_time=session_time
            if context.auto_mode=='spotter' or force_spotter:
                return self.spotter_payload(context,drivers,session,results,weekend,session_time,driver_info)
            live_last=self.get("CarIdxLastLapTime",[])
            valid_bests=[seconds(r.get("FastestTime")) for r in results.values()]
            session_best=min((v for v in valid_bests if v),default=None)
            if self.confirmed_session_best is not None:
                session_best=min(session_best,self.confirmed_session_best) if session_best else self.confirmed_session_best
            player_driver=next((d for d in drivers if d.get("CarIdx")==player_idx),{})
            player_class_id=player_driver.get("CarClassID")
            lap_pct=self.get("CarIdxLapDistPct",[])
            raw_player_pct=lap_pct[player_idx] if player_idx<len(lap_pct) else None
            player_pct=raw_player_pct if raw_player_pct is not None and raw_player_pct>=-.5 else None
            speed=seconds(self.get("Speed",0),45.0)
            track_length=self.track_metres(self.get("WeekendInfo",{}).get("TrackLength","5 km"))
            standing_rows=[];relative_candidates=[]
            for driver in drivers:
                idx=driver.get("CarIdx")
                if idx is None:continue
                result=results.get(idx,{})
                gap=None
                valid_live_pct=(player_pct is not None and idx<len(lap_pct) and lap_pct[idx] is not None and lap_pct[idx]>=-.5)
                if valid_live_pct:
                    delta_laps=lap_pct[idx]-player_pct
                    while delta_laps>.5:delta_laps-=1
                    while delta_laps<-.5:delta_laps+=1
                    gap=delta_laps*track_length/max(speed,1.0)
                overall_pos=result.get("Position",driver.get("CarIdxPosition",0)) or 0
                class_position=result.get("ClassPosition")
                try:class_pos=int(class_position)+1 if class_position is not None else overall_pos
                except (TypeError,ValueError):class_pos=overall_pos
                row={"idx":idx,"pos":overall_pos,"classPos":class_pos,"classId":driver.get("CarClassID"),
                     "className":driver.get("CarClassShortName") or "","number":str(driver.get("CarNumber","—")),
                     "car":car_label(driver),"brand":car_brand(driver),"driver":driver.get("UserName","Desconocido"),
                     "gap":"TÚ" if idx==player_idx else (self.gap_text(gap) if gap is not None else "—"),
                     "gapSeconds":gap if gap is not None else 0.0,
                     "lastLap":self.lap_text(live_last[idx] if idx<len(live_last) else result.get("LastTime")),
                     "pace":self.delta_text(seconds(result.get("FastestTime")),session_best),"completedLaps":result.get("LapsComplete"),"isPlayer":idx==player_idx}
                standing_rows.append(row)
                if valid_live_pct:relative_candidates.append(row.copy())
            standing_rows.sort(key=lambda row:(row["pos"]==0,row["pos"]))
            overall_player=next((row for row in standing_rows if row["isPlayer"]),None)
            category_rows=[row.copy() for row in standing_rows if row.get("classId")==player_class_id] if player_class_id is not None else [row.copy() for row in standing_rows]
            for row in category_rows:
                row["pos"] = row.get("classPos") or row.get("pos") or 0
            category_rows.sort(key=lambda row: (row["pos"] == 0, row["pos"]))
            player = next((row for row in category_rows if row["isPlayer"]), None)
            relative_player = next((row for row in relative_candidates if row["isPlayer"]), None)
            relative = self.relative_rows(relative_candidates, relative_player) if relative_player else []
            if not relative:
                previous = self.session_state.preserved_payload()
                if previous:
                    relative = previous.get("relative", [])
            weekend = self.get("WeekendInfo", {})
            lap_number = int(self.get("Lap", 0))
            last_lap = seconds(self.get("LapLastLapTime"))
            if last_lap is None and player_idx < len(live_last):
                last_lap = seconds(live_last[player_idx])
            fuel_raw=self.get("FuelLevel")
            fuel=float(fuel_raw) if fuel_raw is not None else None
            completed_raw = self.get("LapCompleted")
            completed_laps = int(completed_raw) if completed_raw is not None else None
            result = results.get(player_idx, {})
            car_completed=self.get('CarIdxLapCompleted',[]) or []
            team_completed=car_completed[context.car_idx] if context.car_idx is not None and context.car_idx<len(car_completed) else None
            if fuel is not None and context.local_driving and team_completed is not None and team_completed>=0:
                self.team_fuel_reference=(fuel,int(team_completed))
                self.team_fuel_reference_valid=True
            if completed_laps is not None and fuel is not None:
                self.update_lap_tracking(completed_laps, player_pct, fuel, last_lap, session_best, result)
            self.coach.capture(self.get("LapDistPct", player_pct), session_time,
                               self.get("Speed"), self.get("Brake"), self.get("Throttle"),
                               on_track=bool(self.get("IsOnTrack", True)) and not self.get("OnPitRoad", False),
                               steering=self.get("SteeringWheelAngle"), gear=self.get("Gear"),
                               yaw_rate=self.get("YawRate"), lat_accel=self.get("LatAccel"))
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
            driving_stint = bool(on_track and not on_pit_road)
            if self.stint_active and not driving_stint:
                frozen = self.coach.freeze_stint_summary()
                if frozen: logger.info("COACH STINT SUMMARY frozen priorities=%s", len(frozen))
            elif not self.stint_active and driving_stint:
                self.coach.start_stint()
                logger.info("COACH STINT START")
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
                "self": {"fuel": f"{fuel:.1f} L" if fuel is not None else "—",
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
            payload["coach"] = coach
            payload["strategy"] = self.strategy_payload(fuel)
            pit_flags=self.get("CarIdxOnPitRoad",[]) or [];lap_array=self.get("CarIdxLap",[]) or [];pit_by_idx={idx:bool(pit_flags[idx]) for idx in range(len(pit_flags))};lap_by_idx={idx:lap_array[idx] for idx in range(len(lap_array))}
            payload["raceDirector"]=self.race_director.payload(category_rows,player_idx,pit_by_idx,lap_by_idx)
            payload["enduranceStrategy"]=self.endurance_strategy_payload(fuel,lap_number,completed_for_strategy,average_lap,session_time,driver_info,player_driver.get("UserName","Piloto"))
            in_front=min((r for r in relative if r.get('gapSeconds') is not None and r['gapSeconds']>0),key=lambda r:r['gapSeconds'],default=None)
            behind=max((r for r in relative if r.get('gapSeconds') is not None and r['gapSeconds']<0),key=lambda r:r['gapSeconds'],default=None)
            payload["teamContext"]={"autoMode":"driver","carIdx":context.car_idx,"driver":context.current_driver,
                "source":context.source,"fuelSource":"telemetry","ahead":in_front['gap'] if in_front else '—',
                "behind":behind['gap'] if behind else '—',"remainingTime":clock_text(self.get('SessionTimeRemain')),
                "stintLaps":max(0,completed_for_strategy-(self.strategy_stint_start_lap if self.strategy_stint_start_lap is not None else completed_for_strategy)),
                "teamChoices":[{'idx':context.car_idx,'label':f"#{player_driver.get('CarNumber','—')} · {player_driver.get('TeamName') or player_driver.get('UserName') or '—'}"}] if context.car_idx is not None else []}
            payload["teamDebug"]=self.team_diagnostics(context)
            raw_session_state = self.get("SessionState")
            try:
                ended = int(raw_session_state) in (5, 6)
            except (TypeError, ValueError):
                ended = False
            payload["sessionSummary"] = {"active": bool(ended and in_garage), "bestLap": coach["bestLap"],
                                         "optimalLap": coach["optimalLap"], "potential": coach["potential"],
                                         "lapCount": self.coach.completed, "priorities": self.coach.summary_priorities()}
            return payload
        finally:
            self.ir.unfreeze_var_buffer_latest()

    def apply_spotter_event(self,event):
        if not isinstance(event,dict):return 'Evento inválido'
        consumption=self.strategy_settings.get('consumptionLiters') or (sum(self.fuel_per_lap[-8:])/len(self.fuel_per_lap[-8:]) if self.fuel_per_lap else None)
        completed=self.team_completed_now
        fuel=self.spotter_control.fuel_at(completed,consumption)
        if fuel is None and self.team_fuel_reference_valid and self.team_fuel_reference and completed is not None:
            fuel=estimated_team_fuel(*self.team_fuel_reference,completed,consumption)
        if fuel is None and self.spotter_control.pit_pending:fuel=self.spotter_pre_pit_fuel
        error=self.spotter_control.apply(event,lap=completed,tank_capacity=self.strategy_settings.get('tankCapacityLiters'),projected_fuel=fuel)
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
        car=next((d for d in drivers if d.get('CarIdx')==idx),{}) if idx is not None else {}
        result=results.get(idx,{}) if idx is not None else {}
        lap=at('CarIdxLap',idx)
        completed=at('CarIdxLapCompleted',idx)
        if completed is None:completed=result.get('LapsComplete')
        completed=int(completed) if completed is not None and completed>=0 else None
        last_lap=seconds(at('CarIdxLastLapTime',idx)) or seconds(result.get('LastTime'))
        pace=self.strategy_settings.get('averageLapSeconds') or last_lap
        consumption=self.strategy_settings.get('consumptionLiters') or (sum(self.fuel_per_lap[-8:])/len(self.fuel_per_lap[-8:]) if self.fuel_per_lap else None)
        estimated_fuel=estimated_team_fuel(*self.team_fuel_reference,completed,consumption) if self.team_fuel_reference_valid and self.team_fuel_reference and completed is not None else None
        pct=at('CarIdxLapDistPct',idx)
        pit=at('CarIdxOnPitRoad',idx)
        self.team_completed_now=completed
        if pit is True and not self.strategy_last_on_pit:
            self.spotter_pre_pit_fuel=self.spotter_control.fuel_at(completed,consumption)
            if self.spotter_pre_pit_fuel is None:self.spotter_pre_pit_fuel=estimated_fuel
            self.spotter_control.pit_transition(True,completed)
            self.manual_stop_counted=True
        manual_fuel=self.spotter_control.fuel_at(completed,consumption)
        if self.spotter_control.fuel_source=='PENDIENTE':estimated_fuel=None
        elif manual_fuel is not None:estimated_fuel=manual_fuel
        if idx is not None and completed is not None:
            if self.strategy_stint_start_lap is None and pit is False:
                self.strategy_stint_start_lap=completed
                self.active_stint_driver=self.manual_team_driver or context.current_driver
            current_name=self.manual_team_driver or context.current_driver
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
            if pit is True and not self.strategy_last_on_pit:
                self.team_fuel_reference_valid=False # Refueling amount is not exposed to the remote client.
                estimated_fuel=None
            if pit is True and not self.strategy_last_on_pit and self.strategy_stint_start_lap is not None:
                stint_laps=max(0,completed-self.strategy_stint_start_lap)
                if stint_laps:
                    previous=self.strategy_completed_stints[-1].get('driver') if self.strategy_completed_stints else None
                    driver=self.active_stint_driver or self.manual_team_driver or context.current_driver or '—'
                    self.strategy_completed_stints.append({'number':self.strategy_stops_completed+1,
                        'laps':stint_laps,'driver':driver,'double':previous==driver,'endLap':completed})
                    self.strategy_stops_completed+=1
                self.strategy_stint_start_lap=None
                self.active_stint_driver=None
            if pit is not None:self.strategy_last_on_pit=bool(pit)
        class_id=car.get('CarClassID')
        class_rows=[];live=[]
        for driver in drivers:
            other=driver.get('CarIdx')
            if other is None or other<0 or driver.get('IsSpectator') or (class_id is not None and driver.get('CarClassID')!=class_id):
                continue
            race=results.get(other,{})
            position=race.get('ClassPosition')
            position=int(position)+1 if position is not None else 0
            other_pct=at('CarIdxLapDistPct',other)
            other_lap=at('CarIdxLap',other)
            other_completed=at('CarIdxLapCompleted',other)
            if other_completed is None:other_completed=race.get('LapsComplete')
            gap=0.0 if other==idx else None
            position_data=relative_position(completed,pct,other_completed,other_pct,pace) if other!=idx else (0.0,'EQUIPO')
            if position_data is not None:gap,label=position_data
            else:label='EQUIPO' if other==idx else '—'
            row={'idx':other,'pos':position,'classPos':position,'classId':driver.get('CarClassID'),
                 'className':driver.get('CarClassShortName') or '', 'number':str(driver.get('CarNumber','—')),
                 'car':car_label(driver),'brand':car_brand(driver),'driver':driver.get('UserName') or '—',
                 'gap':label,'gapSeconds':gap,'lastLap':self.lap_text(at('CarIdxLastLapTime',other) or race.get('LastTime')),
                 'pace':'—','isPlayer':other==idx}
            class_rows.append(row)
            if other_pct is not None and other_pct>=0 and (other==idx or gap is not None):live.append(row.copy())
        class_rows.sort(key=lambda row:(not row['pos'],row['pos'] if row['pos'] else results.get(row['idx'],{}).get('Position',999)))
        for rank,row in enumerate(class_rows,1):
            if not row['pos']:row['pos']=rank;row['classPos']=rank
        own=next((row for row in class_rows if row['isPlayer']),None)
        live_own=next((row for row in live if row['isPlayer']),None)
        relative=self.relative_rows(live,live_own) if live_own else []
        standing=self.position_window(class_rows,own) if own else []
        ahead=min((row for row in relative if row.get('gapSeconds') is not None and row['gapSeconds']>0),key=lambda row:row['gapSeconds'],default=None)
        behind=max((row for row in relative if row.get('gapSeconds') is not None and row['gapSeconds']<0),key=lambda row:row['gapSeconds'],default=None)
        driver=self.manual_team_driver or context.current_driver or '—'
        team_choices=[{'idx':d.get('CarIdx'),'label':f"#{d.get('CarNumber','—')} · {d.get('TeamName') or d.get('UserName') or '—'}"}
                      for d in drivers if isinstance(d,dict) and d.get('CarIdx') is not None
                      and d.get('CarIdx')>=0 and not d.get('IsSpectator')
                      and (context.team_id is None or d.get('TeamID')==context.team_id)]
        strategy=self.endurance_strategy_payload(estimated_fuel,lap or 0,completed or 0,pace,session_time,
                                                 driver_info,driver,spotter=True) if idx is not None else {'available':False,'reason':'No se identificó el coche del equipo.'}
        pit_flags=arrays['CarIdxOnPitRoad'];lap_array=arrays['CarIdxLap']
        race_director=self.race_director.payload(class_rows,idx,
            {i:bool(flag) for i,flag in enumerate(pit_flags)},
            {i:value for i,value in enumerate(lap_array)}) if own else {'rival':'—','status':'Esperando coche del equipo.'}
        self.session_state.update_runtime(session_time=session_time,connected=True,
            on_track=bool(pct is not None and pct>=0),on_pit_road=bool(pit),in_garage=False)
        return {'appVersion':installed_version(),'connected':True,'demo':False,
            'teamContext':{'autoMode':'spotter','carIdx':idx,'driver':driver,'source':context.source,'teamChoices':team_choices,
                           'fuelSource':'estimated' if estimated_fuel is not None else 'unavailable','gapSource':'estimated-car-progress',
                           'ahead':ahead['gap'] if ahead else '—','behind':behind['gap'] if behind else '—',
                           'remainingTime':clock_text(self.get('SessionTimeRemain')),'completedLaps':completed,
                           'lapDistPct':pct,'onPitRoad':pit,'fuelState':self.spotter_control.fuel_source if self.spotter_control.events or self.spotter_control.pit_pending else ('ESTIMADO' if estimated_fuel is not None else 'NO DISPONIBLE'),
                           'lastStopLap':self.spotter_control.last_stop_lap,'manualEvents':self.spotter_control.events[-12:],'controlError':self.spotter_event_error,
                           'stintLaps':max(0,(completed or 0)-(self.strategy_stint_start_lap if self.strategy_stint_start_lap is not None else (completed or 0)))},
            'header':{'car':car_label(car) if car else 'COCHE DEL EQUIPO SIN IDENTIFICAR',
                      'track':weekend.get('TrackDisplayName','Pista'),'driver':driver,
                      'position':f"P{own['pos']}" if own else 'P—',
                      'lap':f'VUELTA {lap}' if lap is not None else 'VUELTA —',
                      'state':self.session_type_text(session.get('SessionType','EN SESIÓN'))},
            'self':{'fuel':f'≈ {estimated_fuel:.1f} L · ESTIMADO' if estimated_fuel is not None else '—','lastUse':f'{consumption:.2f} L/v · EST.' if consumption else '—',
                    'bestUse':'—','worstUse':'—','lastLap':self.lap_text(last_lap),
                    'bestLap':'—','laps':[],'wear':{'FL':'—','FR':'—','RL':'—','RR':'—'},
                    'pit':'EN BOXES' if pit else 'EN PISTA' if pct is not None and pct>=0 else 'SIN DATOS',
                    'pitWindow':'—','nextStop':strategy.get('boxLap','—')},
            'lastLapSummary':None,'relative':relative,'standing':standing,
            'capabilities':{'coachControls':False},'coach':{},'strategy':{},
            'raceDirector':race_director,'enduranceStrategy':strategy,
            'sessionSummary':{'active':False},'teamDebug':dict(self.team_diagnostics(context),spotterPayloadReady=bool(idx is not None),relativeRows=len(relative),standingRows=len(standing),classId=class_id,lap=lap,completedLap=completed,lapDistPct=pct,onPitRoad=pit,fuelState=self.spotter_control.fuel_source,fuelSource='MANUAL' if manual_fuel is not None else 'ESTIMADO' if estimated_fuel is not None else 'NO DISPONIBLE',strategySource='SDK + MANUAL' if self.spotter_control.events else 'SDK + ESTIMACIÓN')}

    def reset_session_tracking(self):
        self.last_lap_number=None; self.lap_history=[]; self.last_fuel=None; self.fuel_at_lap_start=None
        self.fuel_per_lap=[]; self.last_player_pct=None; self.lap_started_at=None; self.sector_marks=[]
        self.best_sectors=[None,None,None]; self.last_lap_summary=None; self.last_recorded_lap_time=None
        self.pending_lap=None; self.confirmed_session_best=None; self.personal_session_best=None
        self.personal_lap_clean=False; self.personal_incidents=None; self.coach=LapCoach(); self.stint_active=False; self.race_director=RaceDirector(); self.strategy_completed_stints=[]; self.strategy_stint_start_lap=None; self.strategy_stops_completed=0; self.strategy_last_on_pit=False; self.strategy_target_total_stops=None;self.team_fuel_reference=None;self.team_fuel_reference_valid=False;self.team_car_idx=None;self.team_id=None;self.active_stint_driver=None;self.spotter_control=SpotterControl();self.team_completed_now=None;self.spotter_pre_pit_fuel=None;self.manual_stop_counted=False;self.spotter_event_error=None

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

    def update_lap_tracking(self,lap_number,lap_pct,fuel,last_lap,session_best,result=None):
        completed=seconds(last_lap);result=result or {};incidents=self.get("PlayerCarMyIncidentCount")
        clean_now=(incidents is not None and self.get("PlayerTrackSurface")==3 and not self.get("OnPitRoad",False) and not self.get("PlayerCarTowTime",0))
        self.personal_lap_clean=(self.personal_lap_clean and clean_now and incidents==self.personal_incidents)
        if self.last_lap_number is None:
            self.confirmed_session_best=None;prior_lap=result.get("FastestLap",0)
            self.personal_session_best=seconds(result.get("FastestTime")) if 0<prior_lap<=lap_number else None
            self.personal_lap_clean=False;self.personal_incidents=incidents;self.lap_history,self.fuel_per_lap=[],[]
            self.last_lap_summary=self.pending_lap=None;self.last_lap_number=lap_number;self.last_recorded_lap_time=completed;self.fuel_at_lap_start=None;return
        if lap_number<self.last_lap_number:return
        if lap_number>self.last_lap_number:
            usage=self.fuel_at_lap_start-fuel if self.fuel_at_lap_start is not None else None
            self.pending_lap={"lap":lap_number,"usage":usage,"sectors":[],"previousTime":self.last_recorded_lap_time,"valid":self.personal_lap_clean}
            self.personal_lap_clean=clean_now;self.personal_incidents=incidents;self.fuel_at_lap_start=fuel
            self.last_lap_number=lap_number
        if self.pending_lap and completed:
            numbered_confirmation=(result.get("LapsComplete")==self.pending_lap["lap"] and seconds(result.get("LastTime")) is not None and abs(float(result["LastTime"])-completed)<.001)
            if completed!=self.pending_lap["previousTime"] or numbered_confirmation:
                sdk_best=seconds(self.get("LapBestLapTime"))
                if self.get("LapBestLap")==self.pending_lap["lap"] and sdk_best is not None and abs(sdk_best-completed)<.001:
                    self.pending_lap["valid"]=True
                self.finalize_lap(self.pending_lap,completed,session_best)
                logger.info("LAP COMPLETED %s valid=%s time=%.3f",self.pending_lap["lap"],self.pending_lap["valid"],completed)
                self.pending_lap=None

    def finalize_lap(self,pending,completed,session_best):
        usage=pending["usage"]
        if usage and 0<usage<30:
            self.fuel_per_lap.append(usage);self.fuel_per_lap=self.fuel_per_lap[-10:]
        sectors=pending["sectors"];prior_best=self.personal_session_best
        self.lap_history.append({"lap":pending["lap"],"time":completed,"sectors":sectors,"priorBest":prior_best,"fuelUse":usage})
        self.lap_history=self.lap_history[-10:]
        for index,value in enumerate(sectors if pending.get("valid") else []):
            if self.best_sectors[index] is None or value<self.best_sectors[index]:self.best_sectors[index]=value
        self.confirmed_session_best=min(self.confirmed_session_best,completed) if self.confirmed_session_best else completed
        self.last_lap_summary={"lap":pending["lap"],"time":self.lap_text(completed),"sessionBest":self.lap_text(prior_best),"delta":self.delta_text(completed,prior_best),"expiresAt":time.time()+6}
        if pending.get("valid") and (prior_best is None or completed<prior_best):self.personal_session_best=completed
        coach_ok=self.coach.finish(completed,pending.get("valid"))
        self.recorder.write({"type":"lap","lap":pending["lap"],"valid":bool(pending.get("valid")),"coachAccepted":bool(coach_ok),"officialTime":round(completed,4),"fuelUse":round(usage,3) if usage else None,"best":self.coach.best_lap,"optimal":self.coach.optimal,"diagnostics":self.coach.last_diagnostics,"telemetry":self.coach.last_lap_record})
        if coach_ok:
            logger.info("COACH GENERATED lap=%s best=%s optimal=%s priorities=%s",pending["lap"],self.coach.best_lap,self.coach.optimal,len(self.coach.advice))
            if self.audio_mode=="lap":
                if self.coach.advice:
                    item=self.coach.advice[0];label=self.coach.location_label(item[0]);logger.info("AUDIO PLAY location=%s zone=%s loss=%.3f",label,item[0],item[1]);self.audio_coach.say(f"{label}. Perdiste {round(item[1]*10)} décimas. {item[2]}. {item[3]}")
                else:self.audio_coach.say(f"Vuelta {pending['lap']}. Sin una pérdida clara para corregir.")
        else:logger.info("COACH SKIPPED lap=%s valid=%s",pending["lap"],pending.get("valid"))
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
        self.strategy_target_total_stops=target;payload["settings"]=dict(payload.get("settings") or {},manualRaceSeconds=settings.get("manualRaceSeconds"),averageLapSeconds=settings.get("averageLapSeconds"),consumptionLiters=settings.get("consumptionLiters"),tankCapacityLiters=settings.get("tankCapacityLiters"),driverNames=settings.get("driverNames",[]),driverAssignments={str(k):v for k,v in self.strategy_driver_assignments.items()});
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
        self.session_state.connected=False;payload=self.session_state.preserved_payload()
        if payload is None:payload=self.demo_payload()
        payload["connected"]=False;payload["demo"]=False;payload["header"]["state"]=message.upper();return payload

    def demo_payload(self):
        rows=[(3,"Ferrari 296 GT3","Alejandro Pérez",12.125,"1:32.184","+0.000"),(4,"Lamborghini Huracán GT3 EVO","R. Bell",10.870,"1:32.223","+0.031"),(5,"Porsche 911 GT3 R","Carlos Díaz",9.092,"1:32.122","+0.105"),(6,"Corvette Z06 GT3.R","J. Martin",6.442,"1:32.271","+0.216"),(7,"BMW M4 GT3","Lucas García",3.218,"1:32.441","+0.336"),(8,"McLaren 720S GT3 EVO","SANTIAGO",0,"1:32.481","+0.217"),(9,"Mercedes-AMG GT3","James Smith",-2.317,"1:32.612","+0.496"),(10,"Porsche 911 GT3 R","Tom Jones",-7.824,"1:32.921","+0.656"),(11,"Audi R8 LMS EVO II","M. Laurent",-11.203,"1:33.004","+0.719"),(12,"Ferrari 296 GT3","D. Werner",-14.614,"1:33.075","+0.796"),(13,"BMW M4 GT3","A. Kim",-17.202,"1:33.191","+0.838"),(14,"Acura NSX GT3 EVO","N. Rossi",-20.310,"1:33.300","+0.934")]
        standing=[{"idx":pos,"pos":pos,"classPos":pos,"classId":1,"className":"GT3","number":str(10+pos),"car":car,"brand":car_brand({"CarScreenName":car}),"driver":name,"gap":"TÚ" if gap==0 else self.gap_text(gap),"gapSeconds":gap,"lastLap":last,"pace":pace,"isPlayer":gap==0} for pos,car,name,gap,last,pace in rows]
        payload={"appVersion":APP_VERSION,"connected":True,"demo":True,
                "header":{"car":"McLaren 720S GT3 EVO","track":"Spa-Francorchamps","driver":"SANTIAGO","position":"P8","lap":"VUELTA 12","state":"CARRERA · DEMO"},
                "self":{"fuel":"48.2 L","lastUse":"2.89 L/v","bestUse":"2.82 L/v","worstUse":"2.97 L/v","lastLap":"1:32.481","bestLap":"1:32.401","laps":[{"lap":10,"time":"1:32.401","delta":"—","consumption":"2.82 L/v"},{"lap":11,"time":"1:32.511","delta":"+0.110","consumption":"2.97 L/v"},{"lap":12,"time":"1:32.481","delta":"+0.080","consumption":"2.89 L/v"}],"wear":{"FL":"96%","FR":"95%","RL":"97%","RR":"96%"},"pit":"EN PISTA","pitWindow":"≈ 25 min","nextStop":"VUELTA 28"},
                "lastLapSummary":{"lap":12,"time":"1:32.481","sessionBest":"1:32.401","delta":"+0.080","expiresAt":self.demo_flash_expires},
                "relative":standing[3:10],"standing":standing[3:10],"capabilities":{"coachControls":True},
                "coach":{"reference":"ÓPTIMA SESIÓN","bestLap":"1:32.401","optimalLap":"1:31.940","potential":"0.461","lapMessage":"T1: frenaste pronto. Retrasa ligeramente la frenada.","primary":{"zone":"T1 +0.31","title":"Frenada temprana","advice":"Retrasa ligeramente la frenada manteniendo la misma velocidad mínima."},"secondary":{"zone":"T7 +0.14","title":"Aceleración tardía","advice":"Prioriza la salida y vuelve al acelerador antes."},"pattern":"T1 · 6/8 vueltas","patternAdvice":"La frenada temprana se repite de forma consistente.","trackMap":{"source":"ÚLTIMO STINT · 8 VUELTAS","points":[{"x":50+36*math.cos(i*2*math.pi/72),"y":50+30*math.sin(i*2*math.pi/72),"pct":i/72} for i in range(73)],"markers":[{"rank":1,"x":73,"y":28,"loss":.31,"label":"Primera frenada","cause":"Frenada temprana"},{"rank":2,"x":28,"y":66,"loss":.14,"label":"Cuarta frenada","cause":"Aceleración tardía"}]}},
                "strategy":{"consumption":"2.89 L/v","nextStop":"VUELTA 28","addFuel":"8.0 L","lapsRemaining":"6.2"},
                "raceDirector":{"mode":"auto","selectedIdx":7,"confidence":"AUTO","rival":"#17 · Lucas García","position":"P7","gap":"+3.218","lastLap":"1:32.441","pit":"EN PISTA","lap":"V12","status":"EN PISTA · +3.218","gapBefore":"—","netGap":"+3.218","candidates":[{"idx":7,"label":"#17 · Lucas García","position":"P7"},{"idx":9,"label":"#19 · James Smith","position":"P9"}]},
                "enduranceStrategy":{"available":True,"state":"yellow","verdict":"AHORRO NECESARIO","remainingTime":"9:43:00","currentStint":"S1 / 12","currentDriver":"SANTIAGO","boxLap":"VUELTA 28","autonomy":"16 vueltas","stopsRemaining":11,"lastStopAvoidable":True,"extensionNeeded":10,"extensionAvailable":11,"targetThisStint":"16 vueltas","base":{"stintLaps":37,"stints":13,"stops":12,"lastStintLaps":9,"projectedLaps":432},"extended":{"stintLaps":38,"stints":12,"stops":11,"lastStintLaps":37,"projectedLaps":433},"timeline":[{"number":1,"laps":16,"driver":"SANTIAGO","double":False,"status":"current","endLap":28},{"number":2,"laps":38,"driver":None,"double":False,"status":"future","endLap":66}],"settings":{"baseStintLaps":37,"extendedStintLaps":38,"pitLossSeconds":30,"manualRaceSeconds":36000,"driverNames":["Santiago","David","Herney"],"driverAssignments":{}}},
                "sessionSummary":{"active":False,"bestLap":"1:32.401","optimalLap":"1:31.940","potential":"0.461","lapCount":12,"priorities":[{"zone":"T1","title":"Frenada temprana recurrente","advice":"Apareció en 6 de las últimas 8 vueltas."},{"zone":"T7","title":"Aceleración tardía","advice":"La mayor oportunidad está en volver antes al acelerador."}]}}
        payload['teamContext']={'autoMode':self.demo_role,'carIdx':8,'driver':'SANTIAGO' if self.demo_role=='driver' else 'DAVID',
                                'source':'demo','fuelSource':'telemetry' if self.demo_role=='driver' else 'unavailable',
                                'ahead':'+3.2 s','behind':'-2.3 s','remainingTime':'9:43:00','stintLaps':12}
        if self.demo_role=='spotter':
            self.team_completed_now=11
            payload['teamContext'].update({'completedLaps':11,'lapDistPct':.4,'onPitRoad':False,
                'teamChoices':[{'idx':8,'label':'#18 · ZRE TEAM'}],
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

async def version_status(request):return web.json_response({"installedVersion":installed_version(),"runtimeVersion":APP_VERSION})
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
                    if setting.get("type")=="settings" and setting.get("key")=="audio" and setting.get("value") in ("off","lap","corners"):source.audio_mode=setting["value"]
                    elif setting.get("type")=="settings" and setting.get("key")=="rival":source.race_director.set_selected(setting.get("value"))
                    elif setting.get("type")=="settings" and setting.get("key")=="strategy":source.apply_strategy_settings(setting.get("value"))
                    elif setting.get("type")=="settings" and setting.get("key")=="role" and setting.get('value') in ('auto','driver','spotter'):
                        role_preference=setting['value']
                    elif setting.get("type")=="settings" and setting.get("key")=="teamCar":
                        value=setting.get('value')
                        source.manual_team_car_idx=int(value) if value not in (None,'','auto') and str(value).isdigit() else None
                    elif setting.get('type')=='spotterEvent':
                        source.apply_spotter_event(setting)
                    elif setting.get("type")=="settings" and setting.get("key")=="teamDriver":
                        source.manual_team_driver=str(setting.get('value') or '').strip()[:60] or None
                    elif setting.get("type")=="settings" and setting.get("key")=="demoRole" and source.force_demo:
                        if setting.get('value') in ('driver','spotter'):source.demo_role=setting['value']
                    elif setting.get("type")=="action" and setting.get("action")=="audio_test":source.audio_coach.say("Prueba de audio correcta. El coach está listo para hablarte al terminar una vuelta.")
                except (ValueError,TypeError):pass
    task=asyncio.create_task(receive())
    try:
        while not ws.closed and not task.done():
            await ws.send_json(source.sample(force_spotter=role_preference=='spotter'));await asyncio.sleep(.10)
    except (ConnectionResetError,ConnectionAbortedError,BrokenPipeError,asyncio.CancelledError):pass
    finally:
        task.cancel()
        try:await task
        except (asyncio.CancelledError,ConnectionResetError,OSError):pass
    return ws

def main():
    parser=argparse.ArgumentParser(description="iRacing GT3 timing dashboard");parser.add_argument("--demo",action="store_true");parser.add_argument("--port",type=int,default=8765);args=parser.parse_args()
    app=web.Application(middlewares=[no_cache_middleware]);app["source"]=DashboardSource(args.demo)
    if start_background_updater is not None:
        start_background_updater();print("ZRE Update: vigilancia automatica activa cada 2 minutos; nunca reinicia una carrera.")
    app.router.add_get("/",index);app.router.add_get("/version",version_status);app.router.add_static("/static/",WEB_ROOT);app.router.add_get("/ws",websocket)
    print(f"Dashboard ready at http://localhost:{args.port} ({'demo' if args.demo else 'iRacing SDK'})")
    web.run_app(app,host="127.0.0.1",port=args.port,print=None)

if __name__=="__main__":main()
