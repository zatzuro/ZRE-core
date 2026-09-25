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
except ModuleNotFoundError:
    from session_state import SessionIdentity, SessionState
    from lap_coach import LapCoach, number
    from audio_coach import AudioCoach
    from session_recorder import SessionRecorder

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

    def get(self,key,default=None):
        try:
            value=self.ir[key]
            return default if value is None else value
        except (KeyError,TypeError,AttributeError):
            return default

    def sample(self):
        if self.force_demo:
            return self.demo_payload()
        if self.connect():
            try:
                payload=self.live_payload()
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

    def live_payload(self):
        self.ir.freeze_var_buffer_latest()
        try:
            drivers=self.get("DriverInfo",{}).get("Drivers",[])
            session_num=int(self.get("SessionNum",0))
            sessions=self.get("SessionInfo",{}).get("Sessions",[])
            session=sessions[session_num] if 0<=session_num<len(sessions) else {}
            results={r.get("CarIdx"):r for r in session.get("ResultsPositions",[])}
            weekend=self.get("WeekendInfo",{})
            player_idx=int(self.get("PlayerCarIdx",0))
            identity=SessionIdentity.from_sdk(weekend,session_num,player_idx)
            session_time=self.get("SessionTime")
            if self.session_state.observe_identity(identity):
                logger.info("SESSION CHANGED");self.reset_session_tracking()
            self.session_key=identity;self.last_session_time=session_time
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
                     "pace":self.delta_text(seconds(result.get("FastestTime")),session_best),"isPlayer":idx==player_idx}
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
            fuel = float(self.get("FuelLevel", 0))
            completed_raw = self.get("LapCompleted")
            completed_laps = int(completed_raw) if completed_raw is not None else None
            result = results.get(player_idx, {})
            if completed_laps is not None:
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
            self.session_state.update_runtime(session_time=session_time, connected=True, on_track=on_track, on_pit_road=on_pit_road, in_garage=in_garage)
            payload = {
                "appVersion": APP_VERSION,
                "connected": True, "demo": False,
                "header": {"car": car_label(player_driver), "track": weekend.get("TrackDisplayName", "Pista"),
                           "driver": player_driver.get("UserName", "Piloto"), "position": f"P{player['pos']}" if player else "P—",
                           "lap": f"VUELTA {lap_number}", "state": self.session_type_text(session.get("SessionType", "EN SESIÓN"))},
                "self": {"fuel": f"{fuel:.1f} L",
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

    def reset_session_tracking(self):
        self.last_lap_number=None; self.lap_history=[]; self.last_fuel=None; self.fuel_at_lap_start=None
        self.fuel_per_lap=[]; self.last_player_pct=None; self.lap_started_at=None; self.sector_marks=[]
        self.best_sectors=[None,None,None]; self.last_lap_summary=None; self.last_recorded_lap_time=None
        self.pending_lap=None; self.confirmed_session_best=None; self.personal_session_best=None
        self.personal_lap_clean=False; self.personal_incidents=None; self.coach=LapCoach(); self.stint_active=False

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
        if not uses:return {}
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

    def lap_rows(self,session_best):
        return [{"lap":e["lap"],"time":self.lap_text(e["time"]),"delta":self.delta_text(e["time"],e["priorBest"]),"consumption":self.use_text(e.get("fuelUse"))} for e in self.lap_history]

    def disconnected_payload(self,message):
        self.session_state.connected=False;payload=self.session_state.preserved_payload()
        if payload is None:payload=self.demo_payload()
        payload["connected"]=False;payload["demo"]=False;payload["header"]["state"]=message.upper();return payload

    def demo_payload(self):
        rows=[(3,"Ferrari 296 GT3","Alejandro Pérez",12.125,"1:32.184","+0.000"),(4,"Lamborghini Huracán GT3 EVO","R. Bell",10.870,"1:32.223","+0.031"),(5,"Porsche 911 GT3 R","Carlos Díaz",9.092,"1:32.122","+0.105"),(6,"Corvette Z06 GT3.R","J. Martin",6.442,"1:32.271","+0.216"),(7,"BMW M4 GT3","Lucas García",3.218,"1:32.441","+0.336"),(8,"McLaren 720S GT3 EVO","SANTIAGO",0,"1:32.481","+0.217"),(9,"Mercedes-AMG GT3","James Smith",-2.317,"1:32.612","+0.496"),(10,"Porsche 911 GT3 R","Tom Jones",-7.824,"1:32.921","+0.656"),(11,"Audi R8 LMS EVO II","M. Laurent",-11.203,"1:33.004","+0.719"),(12,"Ferrari 296 GT3","D. Werner",-14.614,"1:33.075","+0.796"),(13,"BMW M4 GT3","A. Kim",-17.202,"1:33.191","+0.838"),(14,"Acura NSX GT3 EVO","N. Rossi",-20.310,"1:33.300","+0.934")]
        standing=[{"idx":pos,"pos":pos,"classPos":pos,"classId":1,"className":"GT3","number":str(10+pos),"car":car,"brand":car_brand({"CarScreenName":car}),"driver":name,"gap":"TÚ" if gap==0 else self.gap_text(gap),"gapSeconds":gap,"lastLap":last,"pace":pace,"isPlayer":gap==0} for pos,car,name,gap,last,pace in rows]
        return {"appVersion":installed_version(),"connected":True,"demo":True,
                "header":{"car":"McLaren 720S GT3 EVO","track":"Spa-Francorchamps","driver":"SANTIAGO","position":"P8","lap":"VUELTA 12","state":"CARRERA · DEMO"},
                "self":{"fuel":"48.2 L","lastUse":"2.89 L/v","bestUse":"2.82 L/v","worstUse":"2.97 L/v","lastLap":"1:32.481","bestLap":"1:32.401","laps":[{"lap":10,"time":"1:32.401","delta":"—","consumption":"2.82 L/v"},{"lap":11,"time":"1:32.511","delta":"+0.110","consumption":"2.97 L/v"},{"lap":12,"time":"1:32.481","delta":"+0.080","consumption":"2.89 L/v"}],"wear":{"FL":"96%","FR":"95%","RL":"97%","RR":"96%"},"pit":"EN PISTA","pitWindow":"≈ 25 min","nextStop":"VUELTA 28"},
                "lastLapSummary":{"lap":12,"time":"1:32.481","sessionBest":"1:32.401","delta":"+0.080","expiresAt":self.demo_flash_expires},
                "relative":standing[3:10],"standing":standing[3:10],"capabilities":{"coachControls":True},
                "coach":{"reference":"ÓPTIMA SESIÓN","bestLap":"1:32.401","optimalLap":"1:31.940","potential":"0.461","lapMessage":"T1: frenaste pronto. Retrasa ligeramente la frenada.","primary":{"zone":"T1 +0.31","title":"Frenada temprana","advice":"Retrasa ligeramente la frenada manteniendo la misma velocidad mínima."},"secondary":{"zone":"T7 +0.14","title":"Aceleración tardía","advice":"Prioriza la salida y vuelve al acelerador antes."},"pattern":"T1 · 6/8 vueltas","patternAdvice":"La frenada temprana se repite de forma consistente.","trackMap":{"source":"ÚLTIMO STINT · 8 VUELTAS","points":[{"x":50+36*math.cos(i*2*math.pi/72),"y":50+30*math.sin(i*2*math.pi/72),"pct":i/72} for i in range(73)],"markers":[{"rank":1,"x":73,"y":28,"loss":.31,"label":"Primera frenada","cause":"Frenada temprana"},{"rank":2,"x":28,"y":66,"loss":.14,"label":"Cuarta frenada","cause":"Aceleración tardía"}]}},
                "strategy":{"consumption":"2.89 L/v","nextStop":"VUELTA 28","addFuel":"8.0 L","lapsRemaining":"6.2"},
                "raceDirector":{"confidence":"MEDIA","rival":"#17 · Lucas García","status":"Parada completada · sigue siendo rival estratégico","gapBefore":"+1.8 s","netGap":"+0.7 s"},
                "sessionSummary":{"active":False,"bestLap":"1:32.401","optimalLap":"1:31.940","potential":"0.461","lapCount":12,"priorities":[{"zone":"T1","title":"Frenada temprana recurrente","advice":"Apareció en 6 de las últimas 8 vueltas."},{"zone":"T7","title":"Aceleración tardía","advice":"La mayor oportunidad está en volver antes al acelerador."}]}}

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
    async def receive():
        async for message in ws:
            if message.type==web.WSMsgType.TEXT:
                try:
                    import json
                    setting=json.loads(message.data)
                    if setting.get("type")=="settings" and setting.get("key")=="audio" and setting.get("value") in ("off","lap","corners"):source.audio_mode=setting["value"]
                    elif setting.get("type")=="action" and setting.get("action")=="audio_test":source.audio_coach.say("Prueba de audio correcta. El coach está listo para hablarte al terminar una vuelta.")
                except (ValueError,TypeError):pass
    task=asyncio.create_task(receive())
    try:
        while not ws.closed:
            await ws.send_json(source.sample());await asyncio.sleep(.10)
    except (ConnectionResetError,asyncio.CancelledError):pass
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
