import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import runtime_storage27 as guard


class Heartbeat(unittest.TestCase):
    def check(self,state,ident='session-1',fault=False):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            if state is not None:(p/'guard.json').write_text(json.dumps(state))
            if fault:(p/'guard_fault.json').write_text('{}')
            with patch.object(guard,'config',return_value=dict(runtime=folder,installation_id=ident)):
                return guard.guard_health()
    def test_valid(self):
        self.assertIsNone(self.check(dict(wall_time=time.time(),installation_id='session-1')))
    def test_identity(self):
        self.assertEqual(self.check(dict(wall_time=time.time(),installation_id='different')),'runtime_storage_watchdog_identity_mismatch')
    def test_missing(self):
        self.assertEqual(self.check(None),'runtime_storage_watchdog_unavailable')
    def test_stale(self):
        self.assertEqual(self.check(dict(wall_time=time.time()-20,installation_id='session-1')),'runtime_storage_watchdog_stale')
    def test_fault(self):
        self.assertEqual(self.check(None,fault=True),'runtime_storage_fault')


if __name__=='__main__':unittest.main()
