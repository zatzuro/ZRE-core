"""One resolved car identity per SDK frame; keep the local user's identity across swaps.

DriverInfo.Drivers is a roster of current car drivers, not a persistent roster of
all team members. DriverCarIdx and PlayerCarIdx describe the local client view and
must not identify the local *person* after another team member takes the car.
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
    local_user_id: int | str | None = None
    local_driver_name: str | None = None
    observed_driver_car_idx: int | None = None
    sdk_driver_user_id: int | str | None = None
    car_number: str | None = None
    car_class_id: int | str | None = None
    team_name: str | None = None

    @classmethod
    def resolve(cls, driver_info, player_idx, is_on_track_car=None,
                last_team_idx=None, manual_car_idx=None, local_user_id=None,
                local_driver_name=None, last_team_id=None, manual_car_number=None, last_car_number=None):
        info = driver_info or {}
        drivers = [d for d in info.get('Drivers', []) if isinstance(d, dict)]
        player_idx = valid_index(player_idx)
        driver_idx = valid_index(info.get('DriverCarIdx'))
        sdk_user = info.get('DriverUserID')
        cars = {valid_index(d.get('CarIdx')): d for d in drivers
                if not d.get('IsSpectator') and valid_index(d.get('CarIdx')) is not None}
        observed = cars.get(player_idx)
        # Learn the local PERSON only while physically driving. Some team clients
        # keep their PlayerCarIdx and DriverUserID pointed at the team car at swaps.
        if is_on_track_car and observed and (local_user_id is None or str(local_user_id) == str(observed.get('UserID'))):
            local_user_id = observed.get('UserID') or local_user_id
            local_driver_name = observed.get('UserName') or local_driver_name
        team_id = last_team_id
        if team_id in (None, '', 0) and sdk_user not in (None, 0, ''):
            spectator = next((d for d in drivers if d.get('IsSpectator') and str(d.get('UserID')) == str(sdk_user)), None)
            if spectator:team_id = spectator.get('TeamID')
        if team_id in (None, '', 0) and local_user_id is not None:
            match = next((d for d in cars.values() if d.get('UserID') == local_user_id), None)
            team_id = match.get('TeamID') if match else None
        if team_id in ('', 0):
            team_id = None
        candidates = [d for d in cars.values() if team_id is not None and d.get('TeamID') == team_id]
        selected = None
        source = 'unknown'
        for number,label in ((manual_car_number,'manual-number'),(last_car_number,'previous-number')):
            if number in (None,''):continue
            matches=[d for d in cars.values() if str(d.get('CarNumber','')).strip()==str(number).strip()
                     and (label=='manual-number' or team_id is None or d.get('TeamID')==team_id)]
            if len(matches)==1:
                selected,source=matches[0],label
                break
        if selected is None:
            for idx,label in ((manual_car_idx,'manual'),(last_team_idx,'previous')):
                candidate=cars.get(valid_index(idx))
                if candidate and (label=='manual' or team_id is None or candidate.get('TeamID')==team_id):
                    selected,source=candidate,label
                    break
        if selected is None and team_id is not None and len(candidates) == 1:
            selected, source = candidates[0], 'team-id'
        if selected is None and is_on_track_car and observed:
            selected, source = observed, 'local-driving'
        if selected is None and driver_idx is not None and driver_idx == player_idx and observed:
            # A cold spectator session has no prior local driving snapshot. Two SDK
            # pointers agree on an entered race car; expose this as provisional.
            selected, source = observed, 'sdk-car-provisional'
        car_idx = valid_index(selected.get('CarIdx')) if selected else None
        if selected and (team_id is None or source in ('manual','manual-number')):
            team_id = selected.get('TeamID') or None
        current_user = selected.get('UserID') if selected else None
        # An SDK user ID without an independently observed local identity is not
        # evidence that the current driver is the user of this local client.
        same_person = (local_user_id is not None and current_user is not None
                       and str(local_user_id) == str(current_user))
        driving = bool(selected and is_on_track_car and car_idx == player_idx and same_person)
        mode = 'driver' if driving or (local_user_id is None and selected and is_on_track_car and car_idx == player_idx) else 'spotter' if selected else 'driver'
        return cls(car_idx, player_idx, team_id, selected.get('UserName') if selected else None,
                   current_user, driving, mode, source, local_user_id, local_driver_name,
                   driver_idx, sdk_user, str(selected.get('CarNumber')) if selected and selected.get('CarNumber') is not None else None,
                   selected.get('CarClassID') if selected else None, selected.get('TeamName') if selected else None)
