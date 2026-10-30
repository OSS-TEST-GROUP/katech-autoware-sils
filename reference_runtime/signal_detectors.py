"""Geometric virtual loop detectors; simulator-only, never perception outputs."""
import math

def detect(plan, actors):
    demands, occupied, details = set(), set(), {}
    for j in plan['junctions']:
        jid = str(j['id']); inside=[]; calls={}
        cx, cy = j['center_ros'][:2]; ex, ey = j['extent']
        for actor in actors:
            x, y = actor['xy']; fx, fy = actor['forward']
            radius = actor.get('radius', 2.5)
            upstream = False
            if actor['kind'] == 'vehicle':
                for a in j['approaches']:
                    hx, hy = a['heading']; sx, sy = a['stop_ros'][:2]
                    along = (x-sx)*hx + (y-sy)*hy
                    lateral = abs((x-sx)*hy - (y-sy)*hx)
                    aligned = fx*hx+fy*hy > .7
                    if aligned and lateral <= a['detector_half_width_m']:
                        if -plan['detector_distance_m'] <= along <= 1.:
                            demands.add(a['key']);calls.setdefault(a['key'],[]).append(actor['id'])
                        if along <= 1.:
                            upstream = True
            # Pre-stop approach strips are outside the conflict area even when the
            # CARLA bounding rectangle includes them. Other occupants block release.
            if abs(x-cx) <= ex+radius and abs(y-cy) <= ey+radius and not upstream:
                occupied.add(jid);inside.append(actor['id'])
        details[jid] = {'calls':calls,'occupants':inside}
    return demands, occupied, details
