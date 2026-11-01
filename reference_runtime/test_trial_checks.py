import unittest
from trial_checks import cap_confirmed, motion_problem, low_speed_cap, diagnostic_level, arrival_confirmed


class TrialChecks(unittest.TestCase):
    def test_arrival_auto_stop_race(self):
        for mode in (1,2):self.assertTrue(arrival_confirmed(True,True,mode,.02,.3))
    def test_arrival_never_accepts_unconfirmed_stop(self):
        for args in [(False,True,1,0,0),(True,False,1,0,0),(True,True,3,0,0),
                     (True,True,1,.1,0),(True,True,1,0,2),(True,True,1,0,-1),
                     (True,True,1,float('nan'),0),(True,True,1,0,float('inf'))]:
            self.assertFalse(arrival_confirmed(*args))
    def test_diagnostic_byte_and_integer(self):
        for value in range(4):
            self.assertEqual(diagnostic_level(value),value)
            self.assertEqual(diagnostic_level(bytes([value])),value)
        for value in (b'',b'xx',4,-1,'2'):
            with self.assertRaises(ValueError):diagnostic_level(value)
    def test_low_cap_range(self):
        for value in (1,3,5):self.assertEqual(low_speed_cap(value),value/3.6)
        for value in (0,5.01,50,float('nan'),float('inf')):
            with self.assertRaises(ValueError):low_speed_cap(value)
    def test_lower_cap_requires_matching_selected_limit(self):
        self.assertTrue(cap_confirmed(3/3.6,[0,.5,3/3.6],cap=low_speed_cap(3)))
        self.assertFalse(cap_confirmed(5/3.6,[0],cap=low_speed_cap(3)))
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
