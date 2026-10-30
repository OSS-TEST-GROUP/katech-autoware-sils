import unittest
from trial_checks import cap_confirmed, motion_problem


class TrialChecks(unittest.TestCase):
    def test_cap_accepts_stopped_or_limited_plan(self):
        self.assertTrue(cap_confirmed(5/3.6,[0,.1,5/3.6]))
    def test_cap_rejects_empty(self):
        self.assertFalse(cap_confirmed(5/3.6,[]))
    def test_cap_rejects_nan_inf(self):
        for bad in (float('nan'),float('inf'),-float('inf')):
            self.assertFalse(cap_confirmed(bad,[0]))
            self.assertFalse(cap_confirmed(5/3.6,[bad,0]))
    def test_cap_rejects_unapplied_limit(self):
        self.assertFalse(cap_confirmed(50/3.6,[0]))
    def test_cap_rejects_high_forward_and_reverse(self):
        for speed in (2,-2):self.assertFalse(cap_confirmed(5/3.6,[speed]))
    def test_motion_valid(self):
        self.assertIsNone(motion_problem(1.3,.2))
    def test_motion_rejects_speed(self):
        for speed in (3,-3,float('nan'),float('inf')):self.assertIsNotNone(motion_problem(speed,.1))
    def test_motion_rejects_error(self):
        for error in (2.1,-.1,float('nan'),float('inf')):self.assertIsNotNone(motion_problem(1,error))
