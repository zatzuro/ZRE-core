"""Car-index timing for an on-track relative, separate from class classification.

The SDK exposes lap counters and distance, but no official F3 Relative gap per
car. Clock differences here are explicitly estimates. Physical order uses the
shortest signed distance around the circuit; race lap delta is independent.
"""
from math import floor


def relative_position(own_completed, own_pct, other_completed, other_pct, pace):
    if any(v is None for v in (own_completed, own_pct, other_completed, other_pct)):
        return None
    if not (0 <= own_pct <= 1 and 0 <= other_pct <= 1):
        return None
    race_delta = (other_completed + other_pct) - (own_completed + own_pct)
    physical = (other_pct - own_pct + .5) % 1 - .5
    # A car exactly opposite is ambiguous; lap progress breaks that tie.
    if physical == -.5 and race_delta > 0:physical = .5
    if abs(physical)<1e-9 and abs(race_delta)>=1:
        physical=1e-6 if race_delta>0 else -1e-6
    full_laps = floor(abs(race_delta) + 1e-9)
    if full_laps:
        count = full_laps if race_delta > 0 else -full_laps
        label = f'{count:+d} LAP' + ('S' if full_laps != 1 else '')
    elif pace is not None and pace > 0:
        label = f'≈ {physical * pace:+.1f} s · EST.'
    else:
        label = 'EST. SIN RITMO'
    return physical, label


def relative_window(rows, own_idx, before=3, after=3):
    own = next((row for row in rows if row.get('idx') == own_idx), None)
    if own is None:return []
    front = sorted((r for r in rows if r.get('idx') != own_idx and r.get('relativeDelta') is not None and r['relativeDelta'] > 0),
                   key=lambda r:r['relativeDelta'])[:before]
    rear = sorted((r for r in rows if r.get('idx') != own_idx and r.get('relativeDelta') is not None and r['relativeDelta'] < 0),
                  key=lambda r:r['relativeDelta'],reverse=True)[:after]
    return sorted(front,key=lambda r:r['relativeDelta'],reverse=True) + [own] + rear


def estimated_team_fuel(last_fuel, reference_completed, current_completed, consumption):
    if any(v is None for v in (last_fuel, reference_completed, current_completed, consumption)):
        return None
    if consumption <= 0 or current_completed < reference_completed:return None
    return max(0.0,last_fuel-(current_completed-reference_completed)*consumption)
