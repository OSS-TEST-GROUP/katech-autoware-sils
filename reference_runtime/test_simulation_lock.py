import multiprocessing as mp
import tempfile
import unittest
import simulation_lock as lock

def hold(entered,release):
    with lock.scene_transaction():
        with lock.scene_transaction():entered.set();release.wait(3)

class LockTests(unittest.TestCase):
    def test_process_exclusion_and_nested_use(self):
        with tempfile.TemporaryDirectory() as d:
            lock._path=d+'/lock'
            entered,release=mp.Event(),mp.Event()
            second,done=mp.Event(),mp.Event()
            a=mp.Process(target=hold,args=(entered,release));b=mp.Process(target=hold,args=(second,done))
            try:
                a.start();self.assertTrue(entered.wait(2));b.start()
                self.assertFalse(second.wait(.2));release.set()
                self.assertTrue(second.wait(2));done.set()
            finally:
                release.set();done.set();a.join(3);b.join(3)
            self.assertEqual(a.exitcode,0);self.assertEqual(b.exitcode,0)

    def test_exception_releases_lock(self):
        with tempfile.TemporaryDirectory() as d:
            lock._path=d+'/lock'
            with self.assertRaises(ValueError):
                with lock.scene_transaction():raise ValueError('fixture')
            with lock.scene_transaction():pass

if __name__=='__main__':unittest.main()
