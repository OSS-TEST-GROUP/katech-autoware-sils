import unittest
from gui_support import validate_gui, configure_rviz
from container_command import partition_command

class GuiTests(unittest.TestCase):
    def gui(self):return dict(display=':1',socket='/tmp/.X11-unix/X1',authority='/local/session/gui.xauth')
    def spec(self,kind='perception'):
        return dict(kind=kind,image='sha256:'+'a'*64,name='test1',label='test1',runtime='/local/session/run',
            volumes={k:'test-'+k for k in ('map','data','source','models','engines')},domain=224,gui=self.gui())
    def test_local_display(self):validate_gui(self.gui())
    def test_remote_refused(self):
        gui=self.gui();gui['display']='host:1'
        with self.assertRaises(ValueError):validate_gui(gui)
    def test_socket_mismatch_refused(self):
        gui=self.gui();gui['socket']='/tmp/.X11-unix/X0'
        with self.assertRaises(ValueError):validate_gui(gui)
    def test_graphics_auth_readonly(self):
        cmd=partition_command(**self.spec())
        self.assertIn('NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics,display',cmd)
        self.assertIn('type=bind,src=/local/session/gui.xauth,dst=/run/sils-gui/Xauthority,readonly',cmd)
        self.assertNotIn('--privileged',cmd);self.assertNotIn('--ipc=host',cmd)
    def test_cookie_not_shared_with_control(self):
        cmd=partition_command(**self.spec('control'))
        self.assertFalse(any('XAUTHORITY' in arg or 'gui.xauth' in arg for arg in cmd))
    def test_nested_gui_refused(self):
        with self.assertRaises(ValueError):partition_command(**self.spec(),gpu_driver_dir='/tmp/driver')
    def test_host_resource_bounds(self):
        cmd=partition_command(**self.spec());self.assertIn('--memory',cmd);self.assertIn('24g',cmd)
    def test_gui_profile_focus_and_explicit_raw_image(self):
        display={'Name':'RecognitionResultOnImage','Class':'rviz_default_plugins/Image','Topic':{'Value':'/old'}}
        cfg={'Visualization Manager':{'Views':{'Current':{'Target Frame':'viewer','X':4,'Y':2}},
            'Displays':[{'Displays':[display]}]},'Window Geometry':{'RecognitionResultOnImage':{'collapsed':False}}}
        configure_rviz(cfg)
        self.assertEqual(cfg['Visualization Manager']['Views']['Current']['Target Frame'],'base_link')
        self.assertEqual(display['Name'],'Camera6RawImage')
        self.assertEqual(display['Topic']['Value'],'/sensing/camera/camera6/image_raw')
        self.assertNotIn('RecognitionResultOnImage',cfg['Window Geometry'])
    def test_unexpected_gui_display_refused(self):
        cfg={'Visualization Manager':{'Views':{'Current':{}},'Displays':[]},'Window Geometry':{}}
        with self.assertRaises(ValueError):configure_rviz(cfg)
