"""Pure acceptance guards for the explicit low-speed simulator smoke test."""
import math


def cap_confirmed(selected, velocities, cap=5/3.6):
    values=list(velocities)
    return (bool(values) and math.isfinite(selected) and abs(selected-cap)<.01
            and all(math.isfinite(v) and abs(v)<=cap+.05 for v in values))


def motion_problem(speed, error):
    if not math.isfinite(speed) or abs(speed)>2.2:return 'Trial speed guard exceeded'
    if not math.isfinite(error) or error>2. or error<0:return 'Localization evaluation error exceeds 2 m'
    return None
