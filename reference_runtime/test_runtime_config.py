import unittest
from runtime_config import validate


class RuntimeConfig(unittest.TestCase):
    def sample(self):
        return dict(schema=1,simulation_only=True,auto_engage=False,auto_resume=False,
                    carla_host='127.0.0.1',carla_port=2480,ros_domain_id=222,headless=True,
                    carla_map='/Game/map_package/Maps/C_track_1_0_7/C_track_1_0_7')

    def test_local(self):validate(self.sample())
    def test_bridge(self):
        c=self.sample();c['carla_host']='172.17.0.1';validate(c)
    def test_no_remote(self):
        c=self.sample();c['carla_host']='8.8.8.8'
        with self.assertRaises(ValueError):validate(c)
    def test_no_auto_engage(self):
        c=self.sample();c['auto_engage']=True
        with self.assertRaises(ValueError):validate(c)
    def test_explicit_domain(self):
        c=self.sample();c['ros_domain_id']=0
        with self.assertRaises(ValueError):validate(c)
    def test_map_mismatch(self):
        c=self.sample();c['carla_map']='Town01'
        with self.assertRaises(ValueError):validate(c)
    def test_reject_low_inference_quality(self):
        c=self.sample();c['render_quality']='Low'
        with self.assertRaises(ValueError):validate(c)


if __name__=='__main__':unittest.main()
