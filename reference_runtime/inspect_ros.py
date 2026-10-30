"""Inspect and exercise only isolated simulation APIs; never bypass control gates."""
import argparse, json, time
from pathlib import Path
import rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from rosidl_runtime_py.utilities import get_message, get_service
from rosidl_runtime_py.convert import message_to_ordereddict
from rosidl_runtime_py.set_message import set_message_fields
p=argparse.ArgumentParser();p.add_argument('action',choices=['health','init','goal','local-stop','start','stop']);p.add_argument('--seconds',type=float,default=12);a=p.parse_args()
rclpy.init();n=rclpy.create_node('ctrack_v7_check');n.set_parameters([rclpy.Parameter('use_sim_time',value=True)])
latest={};counts={};subs=[]
topics=['/clock','/sensing/gnss/pose_with_covariance','/localization/kinematic_state','/perception/object_recognition/objects','/perception/occupancy_grid_map/map','/perception/traffic_light_recognition/traffic_signals','/ctrack/recognition/diagnostics','/planning/mission_planning/route','/planning/scenario_planning/trajectory','/control/command/control_cmd','/control/command/actuation_cmd','/api/operation_mode/state','/localization/initialization_state']
def receive(topic,msg):
    latest[topic]=msg;counts[topic]=counts.get(topic,0)+1
deadline=time.monotonic()+a.seconds
seen=set()
while time.monotonic()<deadline:
    for topic,types in n.get_topic_names_and_types():
        if topic not in topics or topic in seen:continue
        infos=n.get_publishers_info_by_topic(topic)
        transient=topic in ['/api/operation_mode/state','/planning/mission_planning/route','/localization/initialization_state'] or (infos and all(i.qos_profile.durability==DurabilityPolicy.TRANSIENT_LOCAL for i in infos))
        qos=QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE if transient else ReliabilityPolicy.BEST_EFFORT,durability=DurabilityPolicy.TRANSIENT_LOCAL if transient else DurabilityPolicy.VOLATILE)
        subs.append(n.create_subscription(get_message(types[0]),topic,lambda m,t=topic:receive(t,m),qos));seen.add(topic)
    rclpy.spin_once(n,timeout_sec=.1)
def call(name,values):
    types=dict(n.get_service_names_and_types());assert name in types, name+' unavailable'
    typ=get_service(types[name][0]);c=n.create_client(typ,name);assert c.wait_for_service(timeout_sec=15)
    req=typ.Request();set_message_fields(req,values);f=c.call_async(req);rclpy.spin_until_future_complete(n,f,timeout_sec=30)
    assert f.done(),name+' timeout';result=f.result();print(name, result,flush=True)
    if hasattr(result,'status'):assert result.status.success,result.status
    return result
if a.action=='init':
    msg=latest['/sensing/gnss/pose_with_covariance']
    call('/localization/initialize',{'method':1,'pose_with_covariance':[message_to_ordereddict(msg)]})
elif a.action=='goal':
    goal=json.loads(Path('/results/config/start.json').read_text())['smoke_test_goal']
    call('/api/routing/set_route_points',{'header':{'frame_id':'map','stamp':message_to_ordereddict(n.get_clock().now().to_msg())},'goal':goal})
elif a.action=='local-stop':
    for mode in [3,1]:
        call('/system/operation_mode/change_operation_mode',{'mode':mode})
        end=time.monotonic()+.7
        while time.monotonic()<end:rclpy.spin_once(n,timeout_sec=.1)
elif a.action=='start':
    call('/api/operation_mode/change_to_autonomous',{})
    call('/api/operation_mode/enable_autoware_control',{})
elif a.action=='stop':call('/api/operation_mode/change_to_stop',{})
report={'wall_time':time.time(),'counts':counts,'missing':[t for t in topics if t not in latest]}
for t,m in latest.items():
    if t.endswith('/trajectory'):report[t]={'points':len(m.points),'max_velocity':max((p.longitudinal_velocity_mps for p in m.points),default=0.)}
    elif t.endswith('/objects'):report[t]={'objects':len(m.objects)}
    elif t.endswith('/map'):report[t]={'width':m.info.width,'height':m.info.height}
    elif t.endswith('/diagnostics'):report[t]=json.loads(m.data)
    elif t.endswith('/route'):report[t]={'segments':len(m.segments)}
    else:report[t]=message_to_ordereddict(m)
out=Path('/results/reports')/(a.action+'_'+str(time.time_ns())+'.json');out.write_text(json.dumps(report,indent=2));print(json.dumps({'report':str(out),'counts':counts,'missing':report['missing'],'mode':report.get('/api/operation_mode/state'),'trajectory':report.get('/planning/scenario_planning/trajectory'),'recognition_reason':report.get('/ctrack/recognition/diagnostics',{}).get('reason')},indent=2))
n.destroy_node();rclpy.shutdown()
