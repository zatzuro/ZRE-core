"""Timing from car-index arrays. Distances are race progress, never local-client laps."""

def relative_position(own_completed, own_pct, other_completed, other_pct, pace):
    if any(v is None for v in (own_completed, own_pct, other_completed, other_pct)):
        return None
    if not (0 <= own_pct <= 1 and 0 <= other_pct <= 1):
        return None
    delta = (other_completed + other_pct) - (own_completed + own_pct)
    full_laps=int(abs(delta))
    if full_laps:
        lap_diff=full_laps if delta>0 else -full_laps
        label = f'{lap_diff:+d} VUELTA' + ('S' if full_laps != 1 else '')
    elif pace and pace > 0:
        label = f'≈ {delta*pace:+.1f} s · EST.'
    else:
        label = 'EST. SIN RITMO'
    return delta, label


def estimated_team_fuel(last_fuel, reference_completed, current_completed, consumption):
    if any(v is None for v in (last_fuel, reference_completed, current_completed, consumption)):
        return None
    if consumption <= 0 or current_completed < reference_completed:
        return None
    return max(0.0, last_fuel-(current_completed-reference_completed)*consumption)
