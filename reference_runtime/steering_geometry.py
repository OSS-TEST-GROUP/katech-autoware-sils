"""C-Track Tesla / UE4 PhysX 4W steering adapter; radians, ROS left-positive.

PhysX applies maxSteer to the INNER wheel, then Ackermann-corrects the outer.
UE4 converts steering-curve speed keys from km/h. Do not use world-X speed.
This adapter assumes the verified four-wheel Tesla, zero toe and full Ackermann.
"""
import math

WHEELBASE = 3.0046463520604725
TRACK = 1.6668236525911482
MAX_CENTER = .615  # Original limit; .70 candidate did not pass S-course clearance.

def center_angle(left, right):
    """Equivalent bicycle angle from both measured front-wheel angles."""
    if not all(math.isfinite(v) and abs(v) < math.pi / 2 for v in (left, right)):
        raise ValueError('Invalid front wheel angle')
    a, b = math.tan(left), math.tan(right)
    if abs(a) + abs(b) < 1e-9:
        return 0.
    if a * b <= 0:
        # Near-zero transient / float noise; no unstable harmonic division.
        return math.atan((a + b) / 2)
    return math.atan(2 * a * b / (a + b))

def curve_ratio(speed_mps, curve):
    keys = sorted((float(x), float(y)) for x, y in curve)
    if not keys or not all(math.isfinite(x) and math.isfinite(y) and 0 < y <= 1 for x,y in keys):
        raise ValueError('Invalid steering curve')
    v = abs(speed_mps) * 3.6
    if not math.isfinite(v):
        raise ValueError('Invalid forward speed')
    if v <= keys[0][0]:
        return keys[0][1]
    for (x0,y0),(x1,y1) in zip(keys,keys[1:]):
        if x1 <= x0:
            raise ValueError('Duplicate steering curve speed')
        if v <= x1:
            return y0 + (y1-y0)*(v-x0)/(x1-x0)
    return keys[-1][1]

def normalized_command(desired, forward_mps, curve, max_inner_deg):
    if not math.isfinite(desired) or not 0 < max_inner_deg < 90:
        raise ValueError('Invalid steering command / physical limit')
    desired = max(-MAX_CENTER, min(MAX_CENTER, desired))
    t = math.tan(abs(desired))
    inner = math.atan2(t, 1 - TRACK * t / (2 * WHEELBASE))
    gain = math.radians(max_inner_deg) * curve_ratio(forward_mps, curve)
    return max(-1., min(1., -math.copysign(inner / gain, desired)))

def estimated_wheel_centers(actor_x, actor_y, yaw_ros):
    """Nominal wheel XY, not measured suspension/contact or curb detection."""
    rear = -1.38640197
    c,s = math.cos(yaw_ros), math.sin(yaw_ros)
    return {name: [actor_x+c*x-s*y, actor_y+s*x+c*y]
            for name,x,y in [('FL',rear+WHEELBASE,TRACK/2),
                             ('FR',rear+WHEELBASE,-TRACK/2),
                             ('RL',rear,TRACK/2),('RR',rear,-TRACK/2)]}
