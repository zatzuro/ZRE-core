"""Resolve a team car independently of the local SDK client entry.

DriverInfo.Drivers represents the current driver of a team car after a swap.
Unknown identity is left unknown; a spectator entry is never treated as a car.
"""
from dataclasses import dataclass


def valid_index(value):
    try:
        index = int(value)
        return index if index >= 0 else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class TeamCarContext:
    car_idx: int | None
    local_idx: int | None
    team_id: int | str | None
    current_driver: str | None
    current_user_id: int | str | None
    local_driving: bool
    auto_mode: str
    source: str

    @classmethod
    def resolve(cls, driver_info, player_idx, is_on_track_car=None,
                last_team_idx=None, manual_car_idx=None):
        info = driver_info or {}
        drivers = [d for d in (info.get('Drivers') or []) if isinstance(d, dict)]
        local_idx = valid_index(player_idx)
        client_idx = valid_index(info.get('DriverCarIdx'))
        local_user = info.get('DriverUserID')
        local = next((d for d in drivers if local_user not in (None, 0, '')
                      and d.get('UserID') == local_user), None)
        if local is None and local_user in (None, 0, '') and is_on_track_car:
            local = next((d for d in drivers if valid_index(d.get('CarIdx')) == client_idx), None)
        team_id = local.get('TeamID') if local else None
        if team_id in (None, '', 0):
            team_id = None
        candidates = [d for d in drivers if not d.get('IsSpectator')
                      and valid_index(d.get('CarIdx')) is not None
                      and (team_id is None or d.get('TeamID') == team_id)]
        team_candidates = candidates if team_id is not None else []
        if team_id is None and valid_index(last_team_idx) is not None:
            team_candidates = [d for d in candidates if valid_index(d.get('CarIdx')) == valid_index(last_team_idx)]
        car = None
        source = 'unknown'
        for idx, kind in ((manual_car_idx, 'manual'), (last_team_idx, 'previous')):
            pool = candidates if kind == 'manual' else team_candidates
            match = next((d for d in pool
                          if valid_index(d.get('CarIdx')) == valid_index(idx)), None)
            if idx is not None and match is not None:
                car, source = match, kind
                break
        if car is None and len(team_candidates) == 1:
            car, source = team_candidates[0], 'team-id'
        if car is None and local is not None and not local.get('IsSpectator'):
            idx = valid_index(local.get('CarIdx'))
            car = next((d for d in candidates if valid_index(d.get('CarIdx')) == idx), None)
            if car is not None:
                source = 'local-driver'
        if car is None and local is None and is_on_track_car and local_idx is not None:
            car = next((d for d in candidates if valid_index(d.get('CarIdx')) == local_idx), None)
            if car is not None:
                source = 'local-track'
        idx = valid_index(car.get('CarIdx')) if car else None
        current_user = car.get('UserID') if car else None
        same_user = local_user not in (None, 0, '') and local_user == current_user
        local_driving = bool(car and not (local or {}).get('IsSpectator')
                             and idx == local_idx and (same_user or
                             (local_user in (None, 0, '') and is_on_track_car)))
        # Off track with the same driver is still the driver view (garage/pit).
        same_driver = same_user or (car is local and local is not None)
        mode = 'spotter' if car and not same_driver else 'driver'
        return cls(idx, local_idx, team_id, car.get('UserName') if car else None,
                   current_user, local_driving, mode, source)
