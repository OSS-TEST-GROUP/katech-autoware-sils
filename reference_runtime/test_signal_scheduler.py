import copy, math, unittest
from signal_scheduler import Network

def fixture():
    return dict(green_seconds=20., greenleft_seconds=20., redleft_seconds=10., yellow_seconds=2.,
                minimum_red_seconds=30., startup_all_red_seconds=5., junctions=[
        dict(id=j, clearance_seconds=12., approaches=[
            dict(key=f'{j}_{i}', signal_ids=[f'{j}_{i}']) for i in range(n)])
        for j, n in [(228, 4), (611, 4), (726, 3)]])

class TestNetwork(unittest.TestCase):
    def test_empty(self):
        n = Network(fixture(), 0.)
        for t in range(500):
            self.assertEqual(set(n.update(t, set(), set()).values()), {'red'})

    def test_single_96_second_cycle(self):
        n = Network(fixture(), 0.)
        expected = {0:'red', 5:'green', 25:'greenleft', 45:'yellow', 47:'red',
                    58:'red',59:'redleft',68:'redleft',69:'yellow',71:'red',100:'red',101:'green',121:'greenleft',141:'yellow',143:'red'}
        for t in range(150):
            s = n.update(t, {'726_2'}, set())
            if t in expected:
                self.assertEqual(s['726_2'], expected[t], t)

    def test_all_demands_fair_independent_and_safe(self):
        p = fixture(); n = Network(p, 0.)
        keys = {a['key'] for j in p['junctions'] for a in j['approaches']}
        prev = dict.fromkeys(keys, 'red'); since = dict.fromkeys(keys, -30.)
        grants = dict.fromkeys(keys, 0); simultaneous = False
        for t in range(100000):
            states = n.update(t, keys, set())
            active = 0
            for j in p['junctions']:
                lit = sum(states[a['key']] != 'red' for a in j['approaches'])
                self.assertLessEqual(lit, 1); active += bool(lit)
            simultaneous |= active == 3
            for k, v in states.items():
                if v != prev[k]:
                    duration = t-since[k]
                    if v == 'green':
                        self.assertGreaterEqual(duration, 30); grants[k] += 1
                    elif prev[k] != 'red':
                        self.assertEqual(duration, p[prev[k]+'_seconds'])
                    prev[k], since[k] = v, t
        self.assertTrue(simultaneous)
        self.assertGreater(min(grants.values()), 300)
        for j in p['junctions']:
            values = [grants[a['key']] for a in j['approaches']]
            self.assertLessEqual(max(values)-min(values), 1)

    def test_occupied_and_clearance(self):
        n = Network(fixture(), 0.)
        for t in range(100):
            self.assertEqual(n.update(t, {'726_2'}, {'726'})['726_2'], 'red')
        self.assertEqual(n.update(100, {'726_2'}, set())['726_2'], 'green')

    def test_clock_reset_and_large_jump(self):
        n = Network(fixture(), 0.)
        n.update(5, {'726_2'}, set())
        self.assertEqual(n.update(1000, {'726_2'}, set())['726_2'], 'greenleft')
        self.assertEqual(n.update(1000.1, {'726_2'}, set())['726_2'], 'greenleft')
        self.assertEqual(n.update(0, {'726_2'}, set())['726_2'], 'red')
        self.assertEqual(n.update(4.9, {'726_2'}, set())['726_2'], 'red')
        with self.assertRaises(ValueError): n.update(math.nan, set(), set())

    def test_departed_request_removed(self):
        n = Network(fixture(), 0.)
        n.update(1, {'726_2'}, {'726'})
        self.assertEqual(n.update(5, set(), set())['726_2'], 'red')

    def test_redleft_waits_for_empty_and_delayed_clock_never_skips_clearance(self):
        n=Network(fixture(),0.)
        for t in range(200):
            states=n.update(t,{'726_2','726_1'},{'726'} if t>=47 else set())
            if t>=47:self.assertEqual({states['726_2'],states['726_1']},{'red'})
        self.assertEqual(n.update(200,{'726_2','726_1'},set())['726_1'],'redleft')
        self.assertEqual(n.update(1000,{'726_2','726_1'},set())['726_1'],'yellow')
        self.assertEqual(n.update(1000.1,{'726_2','726_1'},set())['726_1'],'yellow')

    def test_invalid_left_duration(self):
        for val in [0,-1,math.nan,math.inf]:
            p=fixture();p['redleft_seconds']=val
            with self.assertRaises(ValueError):Network(p,0.)

    def test_each_junction_clearance_and_single_demand_period(self):
        p=fixture()
        for j,clearance in zip(p['junctions'],[7,12,10]):j['clearance_seconds']=clearance
        n=Network(p,0.);demands={f'{j["id"]}_0' for j in p['junctions']}
        previous={k:'red' for k in demands};green_starts={k:[] for k in demands}
        for t in range(210):
            states=n.update(t,demands,set())
            for k in demands:
                if states[k]=='green' and previous[k]!='green':green_starts[k].append(t)
                previous[k]=states[k]
        for j,period in zip(p['junctions'],[91,96,94]):
            starts=green_starts[f'{j["id"]}_0']
            self.assertEqual(starts[1]-starts[0],period)

if __name__ == '__main__': unittest.main(verbosity=2)
