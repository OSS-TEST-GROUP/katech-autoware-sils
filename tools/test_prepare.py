import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import prepare

class PrepareTests(unittest.TestCase):
    def row(self):return dict(file='model.onnx',bytes=3,sha256=hashlib.sha256(b'abc').hexdigest(),url='https://github.com/example/release')
    def test_cached_hash_no_network(self):
        with tempfile.TemporaryDirectory() as d, patch('urllib.request.urlopen',side_effect=AssertionError('network')):
            p=Path(d)/'model.onnx';p.write_bytes(b'abc')
            self.assertEqual(prepare.artifact(self.row(),Path(d)),p)
    def test_bad_cache_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'model.onnx';p.write_bytes(b'bad')
            with self.assertRaises(ValueError):prepare.artifact(self.row(),Path(d))
            self.assertEqual(p.read_bytes(),b'bad')
    def test_unsafe_name(self):
        row=self.row();row['file']='../x'
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):prepare.artifact(row,Path(d))
    def test_private_credential_url_rejected(self):
        row=self.row();row['url']='https://user:password@github.com/example'
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):prepare.artifact(row,Path(d))
    def test_existing_source_preserved(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):prepare.sources(Path(d))
    def test_symlink_cache_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'real').write_bytes(b'abc');(root/'model.onnx').symlink_to(root/'real')
            with self.assertRaises(ValueError):prepare.artifact(self.row(),root)

    def test_identified_public_client_without_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            response=io.BytesIO(b'abc');response.geturl=lambda:'https://release-assets.githubusercontent.com/file'
            with patch('urllib.request.urlopen',return_value=response) as opened:
                prepare.artifact(self.row(),Path(d))
                request=opened.call_args.args[0]
                self.assertEqual(request.headers['User-agent'],'katech-autoware-sils/0.1')
                self.assertNotIn('Authorization',request.headers)

if __name__=='__main__':unittest.main()
