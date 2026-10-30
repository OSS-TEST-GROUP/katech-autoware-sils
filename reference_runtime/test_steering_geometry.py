import unittest, math
from steering_geometry import *

class SteeringTest(unittest.TestCase):
    curve = [(0,1),(20,.9),(60,.8),(120,.7)]
    def test_round_trip_physx(self):
        for speed in [0,1,5,13.8889,40]:
            for angle in [-MAX_CENTER,-.615,-.5,-.1,0,.1,.5,.615,MAX_CENTER]:
                cmd = normalized_command(angle,speed,self.curve,70)
                inner = abs(cmd)*math.radians(70)*curve_ratio(speed,self.curve)
                outer = math.atan2(WHEELBASE, TRACK+WHEELBASE/math.tan(inner)) if inner else 0
                sign = 1 if angle >= 0 else -1
                self.assertAlmostEqual(center_angle(sign*inner,sign*outer),angle,places=9)
    def test_sign_symmetry_and_clamp(self):
        for angle in [.1,.4,.615,1.,10.]:
            a = normalized_command(angle,1,self.curve,70)
            b = normalized_command(-angle,1,self.curve,70)
            self.assertAlmostEqual(a,-b)
            self.assertLessEqual(abs(a),1)
        self.assertEqual(normalized_command(10,0,self.curve,70),normalized_command(MAX_CENTER,0,self.curve,70))
    def test_curve_units(self):
        self.assertAlmostEqual(curve_ratio(20/3.6,self.curve),.9)
        self.assertAlmostEqual(curve_ratio(-60/3.6,self.curve),.8)
    def test_both_wheels(self):
        a,b=map(math.radians,[36.7,51.8])
        self.assertTrue(a < center_angle(a,b) < b)
        self.assertAlmostEqual(center_angle(-b,-a),-center_angle(a,b))
    def test_invalid(self):
        with self.assertRaises(ValueError):normalized_command(float('nan'),0,self.curve,70)
        with self.assertRaises(ValueError):center_angle(float('nan'),0)

if __name__ == '__main__': unittest.main()
