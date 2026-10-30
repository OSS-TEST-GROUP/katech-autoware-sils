import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from chase_camera import ChaseFilter, SmoothChaseCamera, angle_delta


class ChaseCameraTests(unittest.TestCase):
    def test_initial_offset(self):
        self.assertEqual(ChaseFilter().update(10, 20, 3, 0, .03, 1), (1, 20, 8, 0))

    def test_smooth_position(self):
        f = ChaseFilter()
        f.update(0, 0, 0, 0, .03, 1)
        a = f.update(1, 0, 0, 0, 1/30, 2)[0]
        b = f.update(1, 0, 0, 0, 1/30, 2)[0]
        self.assertTrue(-9 < a < b < -8)

    def test_shortest_yaw_wrap(self):
        f = ChaseFilter()
        f.update(0, 0, 0, 179, .03, 1)
        result = f.update(0, 0, 0, -179, .03, 2)
        self.assertTrue(0 < angle_delta(result[3], 179) < 2)

    def test_frame_rate_independent(self):
        def run(hz):
            f = ChaseFilter()
            f.update(0, 0, 0, 0, 0, 1)
            for _ in range(hz):
                pose = f.update(1, 0, 0, 10, 1/hz, 2)
            return pose
        for a, b in zip(run(30), run(60)):
            self.assertAlmostEqual(a, b)

    def test_teleport_and_frame_reset(self):
        f = ChaseFilter()
        f.update(0, 0, 0, 0, .03, 10)
        self.assertEqual(f.update(100, 0, 0, 0, .03, 11)[0], 91)
        self.assertEqual(f.update(101, 0, 0, 0, .03, 1)[0], 92)

    def test_stopped_converges_without_drift(self):
        f = ChaseFilter()
        f.update(0, 0, 0, 0, .03, 1)
        for _ in range(200):
            pose = f.update(1, 0, 0, 0, 1/30, 2)
        self.assertAlmostEqual(pose[0], -8)
        self.assertEqual(pose[1:], (0, 5, 0))

    def test_reject_nonfinite(self):
        with self.assertRaises(ValueError):
            ChaseFilter().update(math.nan, 0, 0, 0, .03, 1)

    def test_worker_only_updates_spectator_and_stops(self):
        # Fake world deliberately has no tick/apply_settings/vehicle command API.
        # The helper must function without using any of those interfaces.
        transforms = []
        camera = SmoothChaseCamera(7, hz=60)
        transform = SimpleNamespace(location=SimpleNamespace(x=1, y=2, z=3),
                                    rotation=SimpleNamespace(yaw=0))
        actor = SimpleNamespace(get_transform=lambda: transform)
        snapshot = SimpleNamespace(frame=10, find=lambda ident: actor if ident == 7 else None)
        def write(value):
            transforms.append(value)
            if len(transforms) >= 5:
                camera.stopping.set()
        spectator = SimpleNamespace(set_transform=write)
        world = SimpleNamespace(get_snapshot=lambda: snapshot, get_spectator=lambda: spectator)
        client = SimpleNamespace(set_timeout=lambda _: None, get_world=lambda: world)
        fake = SimpleNamespace(Client=lambda *_: client,
            Location=lambda **kw: kw, Rotation=lambda **kw: kw,
            Transform=lambda loc, rot: (loc, rot))
        with patch.dict('sys.modules', carla=fake):
            camera.start()
            camera.thread.join(2)
            camera.close()
        self.assertFalse(camera.thread.is_alive())
        self.assertEqual(len(transforms), 5)
        self.assertEqual(transforms[-1], ({'x': -8, 'y': 2, 'z': 8}, {'pitch': -20, 'yaw': 0}))


if __name__ == '__main__':
    unittest.main()
