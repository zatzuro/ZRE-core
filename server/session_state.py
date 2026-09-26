"""Session continuity helpers for the iRacing dashboard."""
from copy import deepcopy
from dataclasses import dataclass

@dataclass(frozen=True)
class SessionIdentity:
    session_id: object
    subsession_id: object
    track_id: object
    session_num: int
    player_car_idx: int

    @classmethod
    def from_sdk(cls, weekend, session_num, player_car_idx):
        weekend = weekend or {}
        return cls(
            weekend.get("SessionID"),
            weekend.get("SubSessionID"),
            weekend.get("TrackID"),
            int(session_num),
            int(player_car_idx),
        )

class SessionState:
    def __init__(self):
        self.identity = None
        self.last_session_time = None
        self.connected = False
        self.on_track = False
        self.on_pit_road = False
        self.in_garage = False
        self.last_valid_payload = None

    def observe_identity(self, identity, ignore_car_idx=False):
        changed = self.identity is not None and identity != self.identity
        if ignore_car_idx and self.identity is not None:
            changed = (self.identity.session_id,self.identity.subsession_id,self.identity.track_id,self.identity.session_num) != (identity.session_id,identity.subsession_id,identity.track_id,identity.session_num)
        self.identity = identity
        if changed:
            self.last_valid_payload = None
        return changed

    def update_runtime(self, *, session_time=None, connected=True,
                       on_track=False, on_pit_road=False, in_garage=False):
        self.last_session_time = session_time
        self.connected = connected
        self.on_track = bool(on_track)
        self.on_pit_road = bool(on_pit_road)
        self.in_garage = bool(in_garage)

    def remember_payload(self, payload):
        self.connected = True
        self.last_valid_payload = deepcopy(payload)

    def preserved_payload(self):
        return deepcopy(self.last_valid_payload) if self.last_valid_payload else None
