import hashlib
from pathlib import Path
import tempfile
import unittest
from fetch_centerpoint import fetch, validate


class CenterPointFetch(unittest.TestCase):
    def row(self):
        return dict(file='model.onnx',url='https://awf.ml.dev.web.auto/perception/models/centerpoint/v2/model.onnx',sha256=hashlib.sha256(b'model').hexdigest())

    def test_source(self):validate(self.row())

    def test_traversal(self):
        row=self.row();row['file']='../model.onnx'
        with self.assertRaises(ValueError):validate(row)

    def test_bad_origin(self):
        row=self.row();row['url']=row['url'].replace('awf.ml.dev.web.auto','example.com')
        with self.assertRaises(ValueError):validate(row)

    def test_existing_cache(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'model.onnx';p.write_bytes(b'model')
            self.assertEqual(fetch(self.row(),Path(d),100),p)

    def test_existing_different_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'model.onnx';p.write_bytes(b'other')
            with self.assertRaises(ValueError):fetch(self.row(),Path(d),100)
            self.assertEqual(p.read_bytes(),b'other')

    def test_symlink_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'original').write_bytes(b'model');(p/'model.onnx').symlink_to(p/'original')
            with self.assertRaises(ValueError):fetch(self.row(),p,100)
            self.assertTrue((p/'model.onnx').is_symlink())


if __name__=='__main__':unittest.main()
