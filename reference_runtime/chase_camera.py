"""Render-rate spectator following, independent of signal scheduling and physics.

Only the spectator transform is written. Never tick the world, move the ego,
change sensor transforms, or publish vehicle commands from this helper.
"""
import json
import math
import threading
import time
from pathlib import Path


def angle_delta(target, current):
    return (target - current + 180.0) % 360.0 - 180.0


class ChaseFilter:
    def __init__(self, tau=0.10):
        if tau <= 0:
            raise ValueError('tau must be positive')
        self.tau = tau
        self.pose = None
        self.frame = None
        self.last_ego = None

    def update(self, x, y, z, yaw, dt, frame):
        if not all(math.isfinite(v) for v in (x, y, z, yaw, dt)):
            raise ValueError('Non-finite camera input')
        rad = math.radians(yaw)
        target = (x - 9 * math.cos(rad), y - 9 * math.sin(rad), z + 5, yaw)
        # Reposition immediately after an explicit teleport/world reset; do not
        # sweep through the map. Normal driving is exponentially smoothed.
        reset = (self.pose is None or frame < self.frame or
                 math.dist((x, y, z), self.last_ego) > 25)
        if reset:
            self.pose = target
        else:
            alpha = -math.expm1(-max(0.0, min(dt, 0.25)) / self.tau)
            self.pose = tuple(a + alpha * (b - a) for a, b in zip(self.pose[:3], target[:3])) + (
                (self.pose[3] + alpha * angle_delta(yaw, self.pose[3]) + 180) % 360 - 180,)
        self.last_ego = (x, y, z)
        self.frame = frame
        return self.pose


class SmoothChaseCamera:
    def __init__(self, ego_id, port=2400, hz=30.0,
                 report='/results/reports/chase_camera.json'):
        if hz <= 0:
            raise ValueError('hz must be positive')
        self.ego_id, self.port, self.hz = ego_id, port, hz
        self.report = Path(report)
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._run, name='spectator-camera', daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=2)

    def _report(self, value):
        try:
            tmp = self.report.with_suffix('.tmp')
            tmp.write_text(json.dumps(value, indent=2))
            tmp.replace(self.report)
        except OSError as exc:
            print('Camera diagnostic write failed:', exc, flush=True)

    def _run(self):
        import carla
        while not self.stopping.is_set():
            try:
                # A separate client keeps spectator RPCs off the signal loop.
                client = carla.Client('127.0.0.1', self.port)
                client.set_timeout(1.0)
                world = client.get_world()
                spectator = world.get_spectator()
                smooth = ChaseFilter()
                previous = window = time.monotonic()
                writes = 0
                frames = set()
                max_gap = 0.0
                last_write = None
                while not self.stopping.is_set():
                    start = time.monotonic()
                    snapshot = world.get_snapshot()
                    actor = snapshot.find(self.ego_id)
                    if actor is not None:
                        tr = actor.get_transform()
                        x, y, z, yaw = smooth.update(
                            tr.location.x, tr.location.y, tr.location.z,
                            tr.rotation.yaw, start - previous, snapshot.frame)
                        spectator.set_transform(carla.Transform(
                            carla.Location(x=x, y=y, z=z),
                            carla.Rotation(pitch=-20, yaw=yaw)))
                        writes += 1
                        frames.add(snapshot.frame)
                        if last_write is not None:
                            max_gap = max(max_gap, start - last_write)
                        last_write = start
                    previous = start
                    if start - window >= 5:
                        self._report(dict(wall_time=time.time(), ego_id=self.ego_id,
                            target_hz=self.hz, update_hz=writes / (start - window),
                            source_hz=len(frames) / (start - window),
                            max_update_gap_seconds=max_gap, smoothing_seconds=smooth.tau,
                            status='following' if actor is not None else 'waiting_for_ego'))
                        window = start
                        writes = 0
                        frames.clear()
                        max_gap = 0.0
                    self.stopping.wait(max(0.0, 1 / self.hz - (time.monotonic() - start)))
            except Exception as exc:
                # A camera failure must not stop the signal safety controller.
                self._report(dict(wall_time=time.time(), status='camera_error', error=repr(exc)))
                print('Spectator camera retry:', repr(exc), flush=True)
                self.stopping.wait(1.0)
