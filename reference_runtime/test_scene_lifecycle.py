import unittest
from unittest.mock import Mock
from scene_lifecycle import wait_scene_tick

TIMEOUT = 'time-out of 10000ms while waiting for the simulator, make sure the simulator is ready'


class SceneLifecycleTests(unittest.TestCase):
    def test_live_tick_is_returned(self):
        world=Mock();snapshot=object();world.wait_for_tick.return_value=snapshot
        self.assertIs(wait_scene_tick(world,lambda:True),snapshot)
        world.wait_for_tick.assert_called_once_with(10)

    def test_live_timeout_still_fails(self):
        world=Mock();world.wait_for_tick.side_effect=RuntimeError(TIMEOUT)
        with self.assertRaises(RuntimeError):wait_scene_tick(world,lambda:True)

    def test_requested_shutdown_timeout_is_normal(self):
        world=Mock();world.wait_for_tick.side_effect=RuntimeError(TIMEOUT)
        self.assertIsNone(wait_scene_tick(world,lambda:False))

    def test_unrelated_error_not_suppressed_on_shutdown(self):
        world=Mock();world.wait_for_tick.side_effect=RuntimeError('actor connection failed')
        with self.assertRaises(RuntimeError):wait_scene_tick(world,lambda:False)

    def test_no_phase_update_after_requested_shutdown(self):
        world=Mock();world.wait_for_tick.return_value=object()
        self.assertIsNone(wait_scene_tick(world,lambda:False))


if __name__=='__main__':unittest.main()
