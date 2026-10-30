import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from private_assets import PrivateRelease


class PrivateFetchTests(unittest.TestCase):
    def setUp(self):
        with patch('private_assets.credential',return_value='test-key-not-a-credential'):
            self.api=PrivateRelease('example/private')
        self.row=dict(file='map.tar.gz',bytes=3,sha256=hashlib.sha256(b'abc').hexdigest())
        self.repo={'private':True,'visibility':'private'}
        self.release={'draft':False,'assets':[dict(id=1,name=self.row['file'],size=3,state='uploaded',digest='sha256:'+self.row['sha256'])]}
    def test_download(self):
        with tempfile.TemporaryDirectory() as d,patch.object(self.api,'json',side_effect=[self.repo,self.release]),patch.object(self.api,'request',return_value=io.BytesIO(b'abc')):
            p=self.api.fetch('v1',self.row,Path(d));self.assertEqual(p.read_bytes(),b'abc')
    def test_cached_still_checks_privacy(self):
        with tempfile.TemporaryDirectory() as d,patch.object(self.api,'json',return_value={'private':False,'visibility':'public'}):
            root=Path(d);(root/self.row['file']).write_bytes(b'abc')
            with self.assertRaises(ValueError):self.api.fetch('v1',self.row,root)
    def test_cached_authorized(self):
        with tempfile.TemporaryDirectory() as d,patch.object(self.api,'json',return_value=self.repo) as check,patch.object(self.api,'request',side_effect=AssertionError('no download')):
            root=Path(d);(root/self.row['file']).write_bytes(b'abc')
            self.assertEqual(self.api.fetch('v1',self.row,root),root/self.row['file']);check.assert_called_once()
    def test_bad_download_not_published(self):
        for data in (b'bad',b'abcd',b'ab'):
            with tempfile.TemporaryDirectory() as d,patch.object(self.api,'json',side_effect=[self.repo,self.release]),patch.object(self.api,'request',return_value=io.BytesIO(data)):
                with self.assertRaises(ValueError):self.api.fetch('v1',self.row,Path(d))
                self.assertEqual(list(Path(d).iterdir()),[])
    def test_redirect_never_has_authorization(self):
        redirect=HTTPError('https://api.github.com/repos/example/private/releases/assets/1',302,'redirect',{'Location':'https://release-assets.githubusercontent.com/example?test=1'},None)
        with tempfile.TemporaryDirectory() as d,patch.object(self.api,'json',side_effect=[self.repo,self.release]),patch.object(self.api,'request',side_effect=redirect),patch('private_assets.urllib.request.urlopen',return_value=io.BytesIO(b'abc')) as download:
            self.api.fetch('v1',self.row,Path(d))
            self.assertNotIn('Authorization',download.call_args.args[0].headers)
    def test_unexpected_redirect_rejected(self):
        for url in ('http://release-assets.githubusercontent.com/x','https://attacker.invalid/x'):
            redirect=HTTPError('https://api.github.com/x',302,'redirect',{'Location':url},None)
            with tempfile.TemporaryDirectory() as d,patch.object(self.api,'json',side_effect=[self.repo,self.release]),patch.object(self.api,'request',side_effect=redirect):
                with self.assertRaises(ValueError):self.api.fetch('v1',self.row,Path(d))
    def test_remote_digest_mismatch(self):
        self.release['assets'][0]['digest']='sha256:'+'0'*64
        with tempfile.TemporaryDirectory() as d,patch.object(self.api,'json',side_effect=[self.repo,self.release]):
            with self.assertRaises(ValueError):self.api.fetch('v1',self.row,Path(d))


if __name__=='__main__':unittest.main()
