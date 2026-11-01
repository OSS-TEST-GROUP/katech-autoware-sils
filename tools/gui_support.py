"""Local X11 cookie sharing for an explicitly requested GUI; never use xhost."""
import os
from pathlib import Path
import re
import stat
import subprocess
from container_command import directory

def configure_rviz(config):
    """Adjust only this new GUI profile, never the installed/native defaults."""
    manager=config['Visualization Manager']
    manager['Views']['Current'].update({'Target Frame':'base_link','X':0,'Y':0})
    matches=[]
    def visit(displays):
        for display in displays:
            if display.get('Name')=='RecognitionResultOnImage':matches.append(display)
            visit(display.get('Displays') or [])
    visit(manager['Displays'])
    if len(matches)!=1 or matches[0]['Class']!='rviz_default_plugins/Image':
        raise ValueError('Expected exactly one native traffic image display')
    display=matches[0]
    display['Name']='Camera6RawImage'
    display['Topic']['Value']='/sensing/camera/camera6/image_raw'
    display['Topic']['Reliability Policy']='Best Effort'
    config['Window Geometry'].pop('RecognitionResultOnImage',None)
    config['Window Geometry']['Camera6RawImage']={'collapsed':False}
    return config

def validate_gui(gui):
    if set(gui)!={'display','socket','authority'}:raise ValueError('Explicit X11 connection required')
    if not re.fullmatch(r':[0-9]+',gui['display']):raise ValueError('Only a local X11 display is supported')
    if gui['socket']!='/tmp/.X11-unix/X'+gui['display'][1:]:raise ValueError('X11 socket/display mismatch')
    directory(gui['authority'])
    return gui

def prepare_gui(bundle):
    display=os.environ.get('DISPLAY','')
    gui=validate_gui(dict(display=display,socket='/tmp/.X11-unix/X'+display[1:],authority=str(bundle/'gui.xauth')))
    source=Path(os.environ.get('XAUTHORITY',''))
    if not source.is_file() or source.stat().st_uid!=os.getuid():raise ValueError('Current user Xauthority is required')
    if not stat.S_ISSOCK(Path(gui['socket']).stat().st_mode):raise ValueError('X11 socket unavailable')
    # Capture only this display; never print cookies or pass them in argv.
    result=subprocess.run(['xauth','-f',str(source),'nlist',display],capture_output=True,text=True,check=True,timeout=5)
    rows=result.stdout.splitlines()
    if not rows or any(not re.fullmatch(r'[0-9a-fA-F ]+',line) or len(line)<8 for line in rows):
        raise ValueError('No valid cookie for the requested display')
    authority=Path(gui['authority'])
    with authority.open('xb'):pass
    authority.chmod(0o600)
    # FamilyWild permits the container hostname, but the secret remains scoped
    # to the selected display and is mounted read-only to the GUI partition only.
    subprocess.run(['xauth','-f',str(authority),'nmerge','-'],input='\n'.join('ffff'+line[4:] for line in rows)+'\n',
        capture_output=True,text=True,check=True,timeout=5)
    check_gui(gui)
    return gui

def check_gui(gui):
    validate_gui(gui);authority=Path(gui['authority'])
    if authority.is_symlink() or authority.stat().st_uid!=os.getuid() or authority.stat().st_mode & 0o077:
        raise ValueError('GUI cookie must be private and owned by the current user')
    if not stat.S_ISSOCK(Path(gui['socket']).stat().st_mode):raise ValueError('X11 socket unavailable')
    env=os.environ.copy();env.update(DISPLAY=gui['display'],XAUTHORITY=str(authority))
    subprocess.run(['xdpyinfo','-display',gui['display']],env=env,capture_output=True,check=True,timeout=8)
