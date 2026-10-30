import unittest
from evaluate_signal_trial import permits, evaluate


class SignalTrialTests(unittest.TestCase):
    def test_green_not_left(self):self.assertFalse(permits('green','left'))
    def test_redleft_not_straight(self):self.assertFalse(permits('redleft','straight'))
    def test_greenleft_both(self):
        for movement in ('straight','left'):self.assertTrue(permits('greenleft',movement))
    def test_unknown_and_yellow_never_permit(self):
        for state in ('unknown','yellow','red'):
            for movement in ('straight','left'):self.assertFalse(permits(state,movement))
    def test_no_crossing_not_pass(self):
        self.assertFalse(self.evaluate([])['legal_stopline_crossing_observed'])
    def evaluate(self,rows):
        return evaluate(rows,dict(signal_ids=['1'],heading=[1,0],stop_ros=[10,0,0]),'straight',3)
    def row(self,t,x,state):
        return dict(sim_time=t,wall_time=t+1000,gt_xy=[x,0],speed_mps=1,mode=2,visual_states={'1':state},visual_sim_time=t+5,visual_wall_time=t+1000,
            recognition=dict(source_stamp_ns=int(t*1e9),results=[dict(regulatory_id=1,prediction=dict(label=state))]))
    def test_legal_crossing(self):
        result=self.evaluate([self.row(1,6,'green'),self.row(1.1,7.1,'green')])
        self.assertTrue(result['legal_stopline_crossing_observed'])
        self.assertFalse(result['stop_then_permitted_crossing_observed'])
    def test_red_crossing_fails(self):
        self.assertFalse(self.evaluate([self.row(1,6,'red'),self.row(1.1,7.1,'red')])['legal_stopline_crossing_observed'])
    def test_stale_visual_does_not_pass(self):
        row=self.row(10,7.1,'green');row['visual_wall_time']=1
        self.assertFalse(self.evaluate([self.row(9.9,6,'green'),row])['legal_stopline_crossing_observed'])
    def test_operator_stop_is_not_signal_stop_proof(self):
        rows=[self.row(i*.5,6,'redleft') for i in range(7)]
        for row in rows:row.update(speed_mps=0,mode=1)
        rows.append(self.row(3.5,7.1,'green'))
        result=self.evaluate(rows)
        self.assertTrue(result['legal_stopline_crossing_observed'])
        self.assertEqual(result['stopped_on_nonpermissive_seconds'],0)
    def test_autonomous_stop_then_green(self):
        rows=[self.row(i*.5,6,'redleft') for i in range(7)]
        for row in rows:row.update(speed_mps=0)
        rows.append(self.row(3.5,7.1,'green'))
        result=self.evaluate(rows)
        self.assertTrue(result['stop_then_permitted_crossing_observed'])
        self.assertEqual(result['stopped_on_nonpermissive_seconds_by_phase']['redleft'],3)
