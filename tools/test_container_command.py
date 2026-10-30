import unittest
from container_command import partition_command, directory


class ContainerCommandTests(unittest.TestCase):
    def spec(self):
        return dict(kind='perception',image='sha256:'+'a'*64,name='sils-test-perception',label='test1',
            runtime='/tmp/session1',volumes={k:'test-'+k for k in ('map','data','source','models','engines')},domain=123)
    def test_native_gpu_runtime(self):
        cmd=partition_command(**self.spec());self.assertIn('--gpus',cmd)
        self.assertIn('ROS_DOMAIN_ID=123',cmd)
        self.assertIn('type=volume,src=test-map,dst=/autoware_map,readonly',cmd)
    def test_nested_gpu(self):
        cmd=partition_command(**self.spec(),gpu_driver_dir='/tmp/verified-driver')
        self.assertNotIn('--gpus',cmd);self.assertIn('/dev/nvidia0',cmd)
    def test_control_without_gpu(self):
        spec=self.spec();spec['kind']='control';cmd=partition_command(**spec)
        self.assertNotIn('--gpus',cmd);self.assertNotIn('--device',cmd)
    def test_decision_preload(self):
        spec=self.spec();spec['kind']='decision';cmd=partition_command(**spec)
        self.assertTrue(any(x.startswith('LD_PRELOAD=') for x in cmd))
    def test_invalid_kind(self):
        spec=self.spec();spec['kind']='anything'
        with self.assertRaises(ValueError):partition_command(**spec)
    def test_mutable_image_rejected(self):
        spec=self.spec();spec['image']='example:latest'
        with self.assertRaises(ValueError):partition_command(**spec)
    def test_default_domain_rejected(self):
        spec=self.spec();spec['domain']=0
        with self.assertRaises(ValueError):partition_command(**spec)
    def test_paths_reject_injection_and_broad_root(self):
        for value in ('/','/tmp','relative','/tmp/../other','/tmp/a,readonly'):
            with self.assertRaises(ValueError):directory(value)
    def test_volume_alias_rejected(self):
        spec=self.spec();spec['volumes']['models']=spec['volumes']['map']
        with self.assertRaises(ValueError):partition_command(**spec)
