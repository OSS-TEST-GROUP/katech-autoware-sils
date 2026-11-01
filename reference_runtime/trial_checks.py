"""Pure acceptance guards for the explicit low-speed simulator smoke test."""
import math


def diagnostic_level(value):
    if isinstance(value,(bytes,bytearray)) and len(value)==1:value=value[0]
    if type(value) is not int or not 0<=value<=3:raise ValueError('Invalid ROS diagnostic level')
    return value


def low_speed_cap(kmh):
    if not math.isfinite(kmh) or not 1 <= kmh <= 5:
        raise ValueError('Qualification cap must be between 1 and 5 km/h')
    return kmh / 3.6


def arrival_confirmed(full_route, native_arrived, mode, speed, goal_distance):
    # Default AD API switches to STOP upon ARRIVED. Accept that documented
    # transition only with native completion plus measured near-goal standstill.
    return (full_route and native_arrived and mode in (1,2)
            and math.isfinite(speed) and abs(speed)<.1
            and math.isfinite(goal_distance) and 0<=goal_distance<2)


def cap_confirmed(selected, velocities, cap=5/3.6):
    values=list(velocities)
    return (bool(values) and math.isfinite(selected) and abs(selected-cap)<.01
            and all(math.isfinite(v) and abs(v)<=cap+.05 for v in values))


def motion_problem(speed, error):
    if not math.isfinite(speed) or abs(speed)>2.2:return 'Trial speed guard exceeded'
    if not math.isfinite(error) or error>2. or error<0:return 'Localization evaluation error exceeds 2 m'
    return None
