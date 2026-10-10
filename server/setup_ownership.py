"""Fail-closed setup ownership based on independently corroborated SDK identity.

A visual car selection, manual role override, or PlayerCarIdx alone never
authorizes exporting or persisting setup data.
"""
from dataclasses import dataclass, asdict
from server.team_context import valid_index


@dataclass(frozen=True)
class SetupOwner:
    authorized: bool = False
    scope: str = "denied"
    car_idx: int | None = None
    team_id: str | None = None
    driver_user_id: str | None = None
    reason: str = "Identidad del coche sin confirmar"

    def payload(self):
        return asdict(self)


def resolve_setup_owner(context, driver_info, player_idx):
    info = driver_info if isinstance(driver_info, dict) else {}
    drivers = [d for d in (info.get("Drivers") or []) if isinstance(d, dict)]
    cars = {valid_index(d.get("CarIdx")): d for d in drivers
            if not d.get("IsSpectator") and valid_index(d.get("CarIdx")) is not None}
    idx = valid_index(getattr(context, "car_idx", None))
    local_user = getattr(context, "local_user_id", None)
    if idx is None or local_user in (None, "", 0):
        return SetupOwner(reason="Sin coche e identidad local confirmados")
    selected = cars.get(idx)
    if not selected or selected.get("UserID") in (None, "", 0):
        return SetupOwner(reason="Coche observado sin conductor verificable")
    team = selected.get("TeamID")
    team_key = str(team) if team not in (None, "", 0) else None
    user_key = str(local_user)
    if (idx == valid_index(player_idx)
            and (getattr(context, "local_driving", False)
                 or valid_index(info.get("DriverCarIdx")) == idx)
            and str(selected.get("UserID")) == user_key
            and getattr(context, "current_user_id", None) is not None
            and str(context.current_user_id) == user_key):
        return SetupOwner(True, "own", idx, team_key, user_key, "Piloto local confirmado")
    # A spectator may view any vehicle. Require independent team membership
    # from the SDK's LOCAL user's roster/spectator entry, never from manual picks.
    local_members = [d for d in drivers if str(d.get("UserID")) == user_key
                     and d.get("TeamID") not in (None, "", 0)]
    membership = {str(d["TeamID"]) for d in local_members}
    if team_key and team_key in membership and str(getattr(context, "team_id", "")) == team_key:
        return SetupOwner(True, "team", idx, team_key, str(selected.get("UserID")),
                          "Coche y pertenencia al equipo confirmados")
    return SetupOwner(reason="Coche rival o relación con el equipo no verificable")


def same_confirmed_owner(first, current):
    """Allow a teammate handoff on the identical verified team car only."""
    if not first or not current or not first.get("authorized") or not current.get("authorized"):
        return False
    if first.get("car_idx") != current.get("car_idx"):
        return False
    if first.get("scope") == "own" and current.get("scope") == "own":
        return first.get("driver_user_id") == current.get("driver_user_id")
    return bool(first.get("team_id") and first.get("team_id") == current.get("team_id"))
