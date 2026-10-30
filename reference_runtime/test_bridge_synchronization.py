import tempfile
import threading
import unittest
from unittest.mock import patch
import simulation_lock
from bridge_synchronization import protect_initialpose

FIXTURE = '''import threading
class Bridge:
    def initialpose_callback(self, data):
        data()
'''


class BridgeSynchronizationTests(unittest.TestCase):
    def test_idempotent(self):
        once = protect_initialpose(FIXTURE)
        self.assertEqual(protect_initialpose(once), once)
        self.assertEqual(once.count('@scene_transaction()'), 1)

    def test_unknown_shape_rejected(self):
        for source in ('', FIXTURE + FIXTURE):
            with self.assertRaises(ValueError):
                protect_initialpose(source)

    def test_relocation_waits_for_sensor_tick_and_releases_on_error(self):
        namespace = {}
        exec(protect_initialpose(FIXTURE), namespace)
        bridge = namespace['Bridge']()
        entered, attempted, done = threading.Event(), threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(simulation_lock, '_path', directory + '/tick.lock'):
                def relocate():
                    attempted.set()
                    bridge.initialpose_callback(entered.set)
                    done.set()
                with simulation_lock.scene_transaction():
                    thread = threading.Thread(target=relocate)
                    thread.start()
                    self.assertTrue(attempted.wait(2))
                    self.assertFalse(entered.wait(.1))
                thread.join(2)
                self.assertTrue(done.is_set())
                def fail():
                    raise RuntimeError('fixture')
                with self.assertRaises(RuntimeError):
                    bridge.initialpose_callback(fail)
                bridge.initialpose_callback(lambda: None)


if __name__ == '__main__':
    unittest.main()
