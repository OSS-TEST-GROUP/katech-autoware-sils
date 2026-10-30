"""Supervise native ROS launch processes inside a dedicated V7 container."""
import os, sys, json, subprocess, time, signal
from pathlib import Path
from rotating_output27 import start_logged
from runtime_storage27 import guard_health
kind=sys.argv[1]
os.environ['CTRACK_PARTITION']=kind
common=['map_path:=/autoware_map','data_path:=/autoware_data','vehicle_model:=sample_vehicle','sensor_model:=carla_sensor_kit','use_sim_time:=true','is_simulation:=true','pointcloud_container_name:=pointcloud_container_'+kind,'glog_name:=glog_'+kind]
procs=[]
def start(name,cmd):
    if name=='perception' and Path('/results/config/ndt_active.json').exists():
        replacements={'localization_pose_source:=carla':'localization_pose_source:=ndt',
            'localization_twist_source:=carla':'localization_twist_source:=gyro_odom',
            'use_carla_ground_truth_localization:=true':'use_carla_ground_truth_localization:=false'}
        cmd=[replacements.get(x,x) for x in cmd]
    if cmd[:2]==['ros2','launch']:cmd=['python3','/code/launch_ros_v7.py',*cmd[2:]]
    p=start_logged(cmd,'/results/logs/'+name+'.log'); procs.append(p); print(name,p.pid,flush=True)
def stop(*_,exit_code=0):
    for p in procs:
        if p.poll() is None:p.send_signal(signal.SIGINT)
    limit=time.monotonic()+15
    while any(p.poll() is None for p in procs) and time.monotonic()<limit:time.sleep(.2)
    for p in procs:p.log_thread.join(timeout=1)
    sys.exit(exit_code)
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
if kind=='perception':
    pose=json.loads(Path('/results/config/start.json').read_text())['spawn']
    start('bridge',['ros2','launch','autoware_carla_interface','autoware_carla_interface.launch.xml','host:=127.0.0.1','port:=2400','timeout:=60','carla_map:=/Game/map_package/Maps/C_track_1_0_7/C_track_1_0_7','vehicle_type:=vehicle.tesla.model3','spawn_point:='+pose,'use_traffic_manager:=false','objects_definition_file:=/results/config/objects.json','input_initial_pose:=/initialpose3d','output_imu_topic:=/sensing/imu/imu_data','output_camera_image_topic:=/sensing/camera/camera6/image_raw','output_camera_info_topic:=/sensing/camera/camera6/camera_info','publish_ground_truth_traffic_lights:=false'])
    start('perception',['ros2','launch','obigo_launch','adsw_perception.launch.xml',*common,'launch_sensing_driver:=false','launch_system_monitor:=false','launch_dummy_diag_publisher:=true','rviz:=true','rviz_respawn:=false','lidar_detection_model:=centerpoint','localization_pose_source:=carla','localization_twist_source:=carla','localization_gnss_enabled:=false','use_carla_ground_truth_localization:=true','all_traffic_light_camera:=[camera6]'])
    start('recognition',['python3','/results/overlay/recognition_node.py','--enable-test','--map','/results/config/signal_map.json','--ros-args','-p','use_sim_time:=true'])
    scene_script='network_scene.py' if Path('/results/config/signal_network_active.json').exists() else 'scene.py'
    start('scene',['python3','/code/'+scene_script])
elif kind=='decision':
    start('decision',['ros2','launch','obigo_launch','adsw_decision.launch.xml',*common,'system_run_mode:=planning_simulation','launch_system_monitor:=false','launch_dummy_diag_publisher:=true','enable_all_modules_auto_mode:=true','rviz:=false'])
elif kind=='control':
    start('control',['ros2','launch','obigo_launch','adsw_control.launch.xml',*common,'launch_vehicle:=true','launch_vehicle_interface:=false','system_run_mode:=planning_simulation','launch_system_monitor:=false','launch_dummy_diag_publisher:=true','rviz:=false'])
    start('bootstrap',['python3','/code/bootstrap.py'])
    if Path('/results/config/ndt_active.json').exists():
        start('localization_guard',['python3','/code/localization_guard.py'])
else:raise ValueError(kind)
while True:
    storage_fault=guard_health()
    if storage_fault or any(p.poll() is not None for p in procs):
        exited=[{'pid':p.pid,'returncode':p.poll()} for p in procs if p.poll() is not None]
        record={'partition':kind,'wall_time':time.time(),'exited':exited,'storage_fault':storage_fault}
        fault=Path('/results/reports')/(kind+'_fault.json')
        if not fault.exists():fault.write_text(json.dumps(record,indent=2))
        print('Child exited; shutting down this partition',exited,flush=True)
        try:subprocess.run([sys.executable,'/code/emergency_stop.py'],timeout=8,check=True)
        except Exception as e:print('STOP request failed:',str(e),flush=True)
        stop(exit_code=1)
    time.sleep(1)
