import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from install_assets import extract, relative, install, verify_manifest
from prepare import digest


class InstallTests(unittest.TestCase):
    def archive(self,folder,rows):
        p=folder/'input.tar'
        with tarfile.open(p,'w') as out:
            for name,kind,link in rows:
                info=tarfile.TarInfo(name);info.type=kind
                if kind==tarfile.REGTYPE:info.size=3;out.addfile(info,io.BytesIO(b'abc'))
                else:info.linkname=link;out.addfile(info)
        return p
    def test_regular(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);src=self.archive(root,[('a/b',tarfile.REGTYPE,'')])
            self.assertEqual(extract(src,root/'out',private=True)['files'],1)
            self.assertEqual((root/'out/a/b').read_bytes(),b'abc')
    def test_traversal_and_absolute(self):
        for name in ('../escape','/escape','a/../../escape','a\\escape'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
                root=Path(d);src=self.archive(root,[(name,tarfile.REGTYPE,'')])
                with self.assertRaises((ValueError,tarfile.FilterError)):extract(src,root/'out')
    def test_private_links(self):
        for kind in (tarfile.SYMTYPE,tarfile.LNKTYPE):
            with tempfile.TemporaryDirectory() as d:
                root=Path(d);src=self.archive(root,[('link',kind,'a')])
                with self.assertRaises(ValueError):extract(src,root/'out',private=True)
    def test_escaping_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);src=self.archive(root,[('escape',tarfile.SYMTYPE,'../../escape')])
            with self.assertRaises(tarfile.FilterError):extract(src,root/'out')
    def test_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);src=self.archive(root,[('a',tarfile.REGTYPE,'')]*2)
            with self.assertRaises(ValueError):extract(src,root/'out')
    def test_special(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);src=self.archive(root,[('fifo',tarfile.FIFOTYPE,'')])
            with self.assertRaises(ValueError):extract(src,root/'out')
    def test_expansion_limit(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);src=self.archive(root,[('a',tarfile.REGTYPE,'')])
            with self.assertRaises(ValueError):extract(src,root/'out',limit=2)
    def test_existing_install_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'sentinel').write_text('keep')
            with self.assertRaises(ValueError):install(root/'download',root,'ctrack')
            self.assertEqual((root/'sentinel').read_text(),'keep')
    def test_manifest_unlisted(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);f=root/'a';f.write_bytes(b'abc')
            (root/'manifest.json').write_text(json.dumps({'files':[dict(path='a',bytes=3,sha256=digest(f))]}))
            self.assertEqual(verify_manifest(root,'manifest.json'),1)
            (root/'extra').write_text('x')
            with self.assertRaises(ValueError):verify_manifest(root,'manifest.json')


if __name__=='__main__':unittest.main()
