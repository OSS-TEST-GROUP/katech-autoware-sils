import unittest
from signal_detectors import detect

class TestDetectors(unittest.TestCase):
    def setUp(self):
        self.plan={'detector_distance_m':60, 'junctions':[{'id':1,'center_ros':[0,0,0],
            'extent':[10,10],'approaches':[{'key':'north','heading':[0,-1],
            'stop_ros':[-2,8,0],'detector_half_width_m':2}]}]}
    def car(self,x,y,forward=(0,-1),kind='vehicle'):
        return {'id':5,'xy':[x,y],'forward':forward,'radius':2,'kind':kind}
    def test_waiting_inside_bounding_box_is_not_occupancy(self):
        d,o,_=detect(self.plan,[self.car(-2,10)])
        self.assertEqual(d,{'north'});self.assertEqual(o,set())
    def test_crossed_stop_line_occupies(self):
        d,o,_=detect(self.plan,[self.car(-2,5)])
        self.assertEqual(d,set());self.assertEqual(o,{'1'})
    def test_opposite_direction_does_not_call(self):
        d,o,_=detect(self.plan,[self.car(-2,10,(0,1))])
        self.assertEqual(d,set());self.assertEqual(o,{'1'})
    def test_far_away(self):
        d,o,_=detect(self.plan,[self.car(-2,80)])
        self.assertEqual((d,o),(set(),set()))
    def test_pedestrian_blocks(self):
        d,o,_=detect(self.plan,[self.car(0,0,kind='walker')])
        self.assertEqual(d,set());self.assertEqual(o,{'1'})

if __name__=='__main__':unittest.main(verbosity=2)
