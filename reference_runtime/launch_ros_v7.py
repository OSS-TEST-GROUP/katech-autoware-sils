"""Give only the ROS launch management node a container-unique name.

ROS Humble otherwise uses its PID, which repeats across PID namespaces.
Child nodes keep their original names and the duplicate-node safety check stays enabled.
"""
import os,sys,json,time,subprocess
from pathlib import Path
from launch import LaunchService, LaunchDescription
from launch.actions import RegisterEventHandler, EmitEvent
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
failure=[]
include_original=LaunchService.include_launch_description
def child_exit(event,context):
    if context.is_shutdown:return []
    command=event.action.process_details.get('cmd',[])
    critical=any('component_container' in str(x) for x in command)
    if event.returncode==0 and not critical:return []  # normal one-shot loader
    record={'wall_time':time.time(),'partition':os.environ['CTRACK_PARTITION'],
            'process':event.process_name,'pid':event.pid,'returncode':event.returncode,'command':command}
    failure.append(record)
    folder=Path('/results/reports')
    for name in [record['partition']+'_fault.json','child_fault_'+str(time.time_ns())+'.json']:
        (folder/name).write_text(json.dumps(record,indent=2))
    print('CTRACK CRITICAL CHILD EXIT: '+json.dumps(record),flush=True)
    try:
        subprocess.run([sys.executable,'/code/emergency_stop.py'],timeout=8,check=True)
    except Exception as e:print('STOP request failed: '+str(e),flush=True)
    return [EmitEvent(event=Shutdown(reason='Critical native process exited; manual recovery required'))]
def include(self,description):
    if not getattr(self,'_ctrack_watch_installed',False):
        self._ctrack_watch_installed=True
        include_original(self,LaunchDescription([RegisterEventHandler(OnProcessExit(on_exit=child_exit))]))
    return include_original(self,description)
LaunchService.include_launch_description=include
from launch_ros import ros_adapters
original=ros_adapters.ROSAdapter.__init__
def initialize(self,*,argv=None,autostart=True):
    name='ctrack_launch_'+os.environ['CTRACK_PARTITION']+'_'+str(os.getpid())
    original(self,argv=['--ros-args','-r','__node:='+name] if argv is None else argv,autostart=autostart)
ros_adapters.ROSAdapter.__init__=initialize
from ros2cli.cli import main
sys.argv=['ros2','launch',*sys.argv[1:]]
result=main()
sys.exit(1 if failure else result)
