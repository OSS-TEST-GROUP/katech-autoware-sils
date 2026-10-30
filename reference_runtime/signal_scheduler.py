"""Simulator split-phase control; no ROS, vehicle commands or perception labels."""
import math


class Junction:
    def __init__(self, spec, plan, now):
        self.spec, self.plan = spec, plan
        self.keys = [a['key'] for a in spec['approaches']]
        self.reset(now)

    def reset(self, now):
        self.phase, self.active = 'all_red', None
        self.since = now
        self.release = now + self.plan['startup_all_red_seconds']
        self.red_since = {k: now - self.plan['minimum_red_seconds'] for k in self.keys}
        self.waiting = {}

    def update(self, now, demands, occupied):
        # Requests are present-only: a car that leaves a detector relinquishes its request.
        self.waiting = {k: t for k, t in self.waiting.items() if k in demands and k != self.active}
        for k in self.keys:
            if k in demands and k != self.active:
                self.waiting.setdefault(k, now)
        if self.phase == 'all_red':
            eligible = [k for k in self.waiting
                        if now - self.red_since[k] >= self.plan['minimum_red_seconds']]
            if now >= self.release and not occupied and eligible:
                self.active = min(eligible, key=lambda k: (self.waiting[k], self.keys.index(k)))
                self.waiting.pop(self.active)
                self.phase, self.since = 'green', now
        elif self.phase == 'left_clearance':
            # Remove straight permissions and drain the intersection before left-only.
            # The approach stays reserved, but every physical head is red.
            if now >= self.release and not occupied:
                self.phase, self.since = 'redleft', now
        elif now - self.since >= self.plan[
                'yellow_seconds' if self.phase == 'yellow_before_left' else self.phase + '_seconds']:
            # At most one transition per update. A delayed clock never skips clearance.
            if self.phase == 'green':
                self.phase, self.since = 'greenleft', now
            elif self.phase == 'greenleft':
                self.phase, self.since = 'yellow_before_left', now
            elif self.phase == 'yellow_before_left':
                self.phase, self.since = 'left_clearance', now
                self.release = now + self.spec['clearance_seconds']
            elif self.phase == 'redleft':
                self.phase, self.since = 'yellow', now
            else:
                self.red_since[self.active] = now
                self.active, self.phase, self.since = None, 'all_red', now
                self.release = now + self.spec['clearance_seconds']
        display = {'yellow_before_left':'yellow', 'left_clearance':'red'}.get(self.phase, self.phase)
        return {k: display if k == self.active else 'red' for k in self.keys}


class Network:
    def __init__(self, plan, now):
        if not math.isfinite(now):
            raise ValueError('Invalid initial clock')
        self.plan = plan
        for name in ['green_seconds', 'greenleft_seconds', 'redleft_seconds', 'yellow_seconds',
                     'minimum_red_seconds', 'startup_all_red_seconds']:
            if not math.isfinite(plan[name]) or plan[name] <= 0:
                raise ValueError('Invalid duration: ' + name)
        for j in plan['junctions']:
            if not math.isfinite(j['clearance_seconds']) or j['clearance_seconds'] <= 0:
                raise ValueError('Invalid junction clearance')
        self.junctions = [Junction(j, plan, now) for j in plan['junctions']]
        self.last = now

    def update(self, now, demands, occupied):
        if not math.isfinite(now):
            raise ValueError('Invalid simulation clock')
        if now < self.last:
            for j in self.junctions:
                j.reset(now)
        self.last = now
        result = {}
        for j in self.junctions:
            states = j.update(now, demands, str(j.spec['id']) in occupied)
            for a in j.spec['approaches']:
                for ident in a['signal_ids']:
                    if ident in result:
                        raise ValueError('Signal is assigned twice: ' + ident)
                    result[ident] = states[a['key']]
        return result

    def status(self):
        return [{'id': j.spec['id'], 'phase': j.phase, 'active': j.active,
                 'phase_since': j.since, 'waiting': j.waiting,
                 'earliest_clearance_release': j.release} for j in self.junctions]
