import tempfile
from pathlib import Path
import unittest
from session_support import endpoint, check_mount, verify_files, digest, validate_descriptor, check_owned_volumes


class SessionSupportTests(unittest.TestCase):
    def descriptor(self):
        return dict(schema=1,name='example',simulation_only=True,auto_engage=False,map_id='ctrack',
            docker_host='unix:///tmp/docker.sock',parent_host='unix:///var/run/docker.sock',
            images={k:'sha256:'+'1'*64 for k in ('control','decision','perception')},parent=None,
            gpu_driver_dir=None,installation='/data/install',bundle='/local/bundle',stage='/local/bundle/stage')
    def test_explicit_local_socket(self):self.assertEqual(endpoint('unix:///tmp/a.sock'),'unix:///tmp/a.sock')
    def test_remote_docker_refused(self):
        for value in ('tcp://localhost:2375','ssh://host','unix://relative','unix:///tmp/../socket'):
            with self.assertRaises(ValueError):endpoint(value)
    def test_normal_descriptor(self):validate_descriptor(self.descriptor())
    def test_auto_engage_refused(self):
        d=self.descriptor();d['auto_engage']=True
        with self.assertRaises(ValueError):validate_descriptor(d)
    def test_unknown_map_refused(self):
        d=self.descriptor();d['map_id']='Town01'
        with self.assertRaises(ValueError):validate_descriptor(d)
    def test_mutable_image_refused(self):
        d=self.descriptor();d['images']['control']='test:latest'
        with self.assertRaises(ValueError):validate_descriptor(d)
    def test_nested_requires_driver(self):
        d=self.descriptor();d['parent']=dict(name='parent',id='2'*64)
        with self.assertRaises(ValueError):validate_descriptor(d)
    def test_nested_descriptor(self):
        d=self.descriptor();d['parent']=dict(name='parent',id='2'*64);d['gpu_driver_dir']='/tmp/driver'
        validate_descriptor(d)
    def test_mount_identity_and_writable_required(self):
        current=dict(source='/dev/test',target='/data',fstype='ext4',uuid='abc',options='rw,relatime')
        check_mount(current,current)
        for key,value in [('uuid','other'),('source','/dev/other'),('options','ro')]:
            changed=dict(current);changed[key]=value
            with self.assertRaises(RuntimeError):check_mount(changed,current)
    def test_hash_verification(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);p=root/'test';p.write_bytes(b'123')
            verify_files(root,[dict(file='test',sha256=digest(p),bytes=3)])
            with self.assertRaises(ValueError):verify_files(root,[dict(file='test',sha256='0'*64)])
    def test_manifest_traversal_refused(self):
        with tempfile.TemporaryDirectory() as name, self.assertRaises(ValueError):
            verify_files(Path(name),[dict(file='../test',sha256='0'*64)])
    def test_manifest_symlink_refused(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);p=root/'actual';p.write_bytes(b'123');(root/'link').symlink_to(p)
            with self.assertRaises(ValueError):verify_files(root,[dict(file='link',sha256=digest(p))])
    def volume_fixture(self):
        volumes={k:'example-'+k for k in ('map','data','source','models','engines')}
        return volumes,[dict(Name=n,Labels={'katech.sils.bundle':'owner'}) for n in volumes.values()]
    def test_owned_volumes(self):
        v,r=self.volume_fixture();check_owned_volumes(v,'owner',r)
    def test_unlabelled_volume_refused(self):
        v,r=self.volume_fixture();r[0]['Labels']=None
        with self.assertRaises(RuntimeError):check_owned_volumes(v,'owner',r)
    def test_foreign_volume_refused(self):
        v,r=self.volume_fixture();r[0]['Labels']['katech.sils.bundle']='foreign'
        with self.assertRaises(RuntimeError):check_owned_volumes(v,'owner',r)
    def test_aliased_volume_refused(self):
        v,r=self.volume_fixture();v['engines']=v['models']
        with self.assertRaises(ValueError):check_owned_volumes(v,'owner',r)
