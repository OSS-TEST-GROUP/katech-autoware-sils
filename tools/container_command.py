"""Portable native partition command construction; never launches by itself.

The supervisor must verify filesystem/image/model identity, runtime ownership,
host networking isolation and heartbeat before executing the returned arguments.
Paths refer to the selected Docker daemon's filesystem, not necessarily the CLI
host. GPU driver binds are for an already verified isolated nested daemon only.
"""
from pathlib import PurePosixPath
import re


def safe_name(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}',value):
        raise ValueError('Invalid owned resource name')
    return value


def directory(value):
    path=PurePosixPath(value)
    if not path.is_absolute() or len(path.parts)<3 or '..' in path.parts or any(c in str(path) for c in ',\n\r'):
        raise ValueError('Explicit safe daemon-local directory required')
    return str(path)


def partition_command(kind,image,name,label,runtime,volumes,domain,gpu_driver_dir=None,gui=None):
    if kind not in ('perception','decision','control'):raise ValueError('Unknown partition')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise ValueError('Resolve and pin image ID before launch')
    safe_name(name);safe_name(label);runtime=directory(runtime)
    if type(domain) is not int or not 1<=domain<=232:raise ValueError('Explicit isolated ROS domain required')
    if set(volumes)!={'map','data','source','models','engines'}:raise ValueError('All explicit volume roles required')
    if len(set(volumes.values()))!=5:raise ValueError('Volume roles must not alias')
    for value in volumes.values():safe_name(value)
    if gui:
        from gui_support import validate_gui
        validate_gui(gui)
        if gpu_driver_dir:raise ValueError('GUI requires the normal host NVIDIA runtime')
    cmd=['run','-d','--name',name,'--label','katech.sils.role='+label,
         '--network','host','--user','1000:1000','--cap-drop','ALL','--security-opt','no-new-privileges',
         '--shm-size','1g','--tmpfs','/tmp:rw,size=2g','--log-driver','local','--log-opt','max-size=10m','--log-opt','max-file=2']
    if not gpu_driver_dir:
        memory,cpus={'perception':('24g','8'),'decision':('8g','4'),'control':('4g','2')}[kind]
        cmd+=['--memory',memory,'--memory-swap',memory,'--cpus',cpus]
    env={'ROS_DOMAIN_ID':str(domain),'ROS_LOCALHOST_ONLY':'1','RMW_IMPLEMENTATION':'rmw_cyclonedds_cpp',
         'CYCLONEDDS_URI':'file:///code/cyclonedds.xml','ROS_LOG_DIR':'/results/logs/ros_'+kind,
         'HOME':'/tmp','PYTHONDONTWRITEBYTECODE':'1',
         'PYTHONPATH':'/code:/repo/ctrack_perception_v2:/repo/aihub188_mobilenetv2/candidate_c:/repo/aihub188_mobilenetv2/carla_town_c:/repo/aihub188_mobilenetv2:/opt/katech-sils/python'}
    binds=[(runtime,'/results',False),(runtime+'/code','/code',True),
           (runtime+'/share/obigo_launch','/opt/autoware/share/obigo_launch',True),
           (runtime+'/config/vehicle_info.param.yaml','/opt/autoware/share/sample_vehicle_description/config/vehicle_info.param.yaml',True),
           (runtime+'/config/sensor_kit_calibration.yaml','/opt/autoware/share/individual_params/config/default/carla_sensor_kit/sensor_kit_calibration.yaml',True)]
    if kind=='perception':
        if gpu_driver_dir:
            gpu_driver_dir=directory(gpu_driver_dir)
            for device in ('nvidia0','nvidiactl','nvidia-uvm'):cmd+=['--device','/dev/'+device]
            binds.append((gpu_driver_dir,'/opt/nvidia',True))
            env['LD_LIBRARY_PATH']='/opt/nvidia:/usr/local/cuda/lib64:/usr/local/cuda/targets/x86_64-linux/lib'
        else:
            cmd+=['--gpus','all'];env['NVIDIA_DRIVER_CAPABILITIES']='compute,utility'
            if gui:
                env.update(DISPLAY=gui['display'],XAUTHORITY='/run/sils-gui/Xauthority',QT_X11_NO_MITSHM='1',
                    NVIDIA_DRIVER_CAPABILITIES='compute,utility,graphics,display')
                binds.extend([(gui['socket'],gui['socket'],True),(gui['authority'],'/run/sils-gui/Xauthority',True)])
        binds.append((runtime+'/signal_network_v1/placements.json','/placements.json',True))
    if kind=='decision':env['LD_PRELOAD']='/opt/autoware/lib/libstop_distance_guard.so:/opt/autoware/lib/libplugin_lifetime.so'
    for src,dst,ro in binds:cmd+=['--mount',f'type=bind,src={src},dst={dst}'+(',readonly' if ro else '')]
    for key,dst,ro in [('map','/autoware_map',True),('data','/autoware_data',False),
                       ('source','/repo',True),('models','/models',True),('engines','/engines',True)]:
        cmd+=['--mount',f'type=volume,src={volumes[key]},dst={dst}'+(',readonly' if ro else '')]
    for key,value in env.items():cmd+=['-e',key+'='+value]
    cmd+=['--entrypoint','/bin/bash',image,'-lc','source /opt/autoware/setup.bash && exec python3 /code/partition.py '+kind]
    return cmd
