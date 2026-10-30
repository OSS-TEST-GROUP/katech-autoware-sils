import sys,unittest,importlib.util
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path


class PoolTests(unittest.TestCase):
    def test_phase_changes_reuse_actors_and_hide_before_show(self):
        with patch.dict(sys.modules,{'carla':SimpleNamespace()}):
            spec=importlib.util.spec_from_file_location('pool_under_test',Path(__file__).with_name('signal_pool.py'))
            mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        events=[]
        class Actor:
            is_alive=True
            def __init__(self,name):self.name=name
            def set_transform(self,p):events.append((self.name,p.location.z))
            def destroy(self):self.is_alive=False;events.append(('destroy',self.name))
        class Scene(mod.PooledSignals):
            def __init__(self):self.heads={};self.states={};self.supports=[];self.created=[]
            def pose(self,p):return SimpleNamespace(location=SimpleNamespace(z=7))
            def mesh(self,name,pose,role):
                actor=Actor(name);self.created.append(actor);return actor
        scene=Scene();p={'regulatory_id':'1'}
        scene.set_state(p,'red');red=scene.heads['1'];events.clear()
        for _ in range(20):
            for state in mod.STATES:scene.set_state(p,state)
        self.assertEqual(len(scene.created),5)
        self.assertFalse(any(e[0]=='destroy' for e in events))
        # Every replacement hides the previous head before showing the next.
        for i in range(0,len(events),2):
            self.assertLess(events[i][1],-100);self.assertEqual(events[i+1][1],7)
        scene.set_state(p,'red');self.assertIs(scene.heads['1'],red)
        scene.destroy();self.assertTrue(all(not a.is_alive for a in scene.created))

if __name__=='__main__':unittest.main()
