import unittest
from copy import deepcopy
from ndt_profile import bounded_step_profile


class NdtProfileTests(unittest.TestCase):
    def baseline(self):
        return {'/**':{'ros__parameters':{
            'ndt':{'step_size':.1,'trans_epsilon':.01,'max_iterations':30,'resolution':2.,
                   'regularization':{'enable':False}},
            'score_estimation':{'converged_param_nearest_voxel_transformation_likelihood':2.3},
            'validation':{'initial_to_result_distance_tolerance_m':3.,'skipping_publish_num':5}}}}
    def test_only_maximum_step_changes(self):
        original=self.baseline();saved=deepcopy(original)
        result=bounded_step_profile(original)
        self.assertEqual(original,saved)
        expected=deepcopy(original);expected['/**']['ros__parameters']['ndt']['step_size']=.05
        self.assertEqual(result,expected)
    def test_idempotent(self):
        result=bounded_step_profile(self.baseline())
        self.assertEqual(bounded_step_profile(result),result)
    def test_unknown_baseline_rejected(self):
        for key,value in [('step_size',.2),('trans_epsilon',.02)]:
            config=self.baseline();config['/**']['ros__parameters']['ndt'][key]=value
            with self.assertRaises(ValueError):bounded_step_profile(config)
    def test_missing_profile_rejected(self):
        for value in ({},{'/**':{}},{'/**':{'ros__parameters':{'ndt':None}}}):
            with self.assertRaises(ValueError):bounded_step_profile(value)
