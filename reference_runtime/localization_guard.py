"""Wall-clock watchdog for the isolated simulator; never enables autonomous mode.

Uses actual NDT/EKF/clock freshness, not ground-truth accuracy or dummy health.
Missing data triggers repeated native STOP requests, including while sim time stalls.
"""
import os,time,json,math,signal
from pathlib import Path
import rclpy
from rclpy.executors import ExternalShutdownException
from geometry_msgs.msg import PoseWithCovarianceStamped, TwistWithCovarianceStamped
from nav_msgs.msg import Odometry
from rosgraph_msgs.msg import Clock
from autoware_adapi_v1_msgs.srv import ChangeOperationMode

assert os.environ.get('ROS_DOMAIN_ID')=='222'
rclpy.init();node=rclpy.create_node('ctrack_localization_guard')
received={};stamps={};finite={};latest={};start=time.monotonic();last_request=0.;pending=None;fault=None;healthy_since=None
folder=Path('/results/ndt_integration_v1');events=(folder/'guard_events.jsonl').open('a',buffering=1)
def receive(key,msg):
    latest[key]=msg
    stamp=msg.clock if key=='clock' else msg.header.stamp
    value=stamp.sec+stamp.nanosec*1e-9
    if stamps.get(key)!=value:received[key]=time.monotonic();stamps[key]=value
    if key not in ['clock','vehicle']:
        p=msg.pose.pose
        finite[key]=all(math.isfinite(v) for v in [p.position.x,p.position.y,p.position.z,p.orientation.x,p.orientation.y,p.orientation.z,p.orientation.w])
subs=[node.create_subscription(Clock,'/clock',lambda m:receive('clock',m),10),
      node.create_subscription(Odometry,'/localization/kinematic_state',lambda m:receive('ekf',m),10),
      node.create_subscription(PoseWithCovarianceStamped,'/localization/pose_estimator/pose_with_covariance',lambda m:receive('ndt',m),10),
      node.create_subscription(TwistWithCovarianceStamped,'/sensing/vehicle_velocity_converter/twist_with_covariance',lambda m:receive('vehicle',m),10)]
client=node.create_client(ChangeOperationMode,'/api/operation_mode/change_to_stop')
def event(kind,**kw):events.write(json.dumps({'wall_time':time.time(),'kind':kind,**kw})+'\n')
try:
    while rclpy.ok():
        rclpy.spin_once(node,timeout_sec=.1);now=time.monotonic()
        if pending and pending.done():
            try:event('stop_response',success=bool(pending.result().status.success))
            except Exception as e:event('stop_error',error=repr(e))
            pending=None
        armed=all(k in received for k in ['clock','ekf','ndt','vehicle']) or now-start>120
        bad=[k for k in ['clock','ekf','ndt','vehicle'] if now-received.get(k,start)>1.5 or not finite.get(k,True)] if armed else []
        if armed and all(k in latest for k in ['ekf','vehicle']):
            estimate=latest['ekf'].twist.twist;measured=latest['vehicle'].twist.twist
            if not all(math.isfinite(v) for v in [estimate.linear.x,estimate.angular.z]):bad.append('nonfinite_twist')
            elif abs(estimate.linear.x-measured.linear.x)>3 or abs(estimate.angular.z-measured.angular.z)>.5:bad.append('twist_inconsistent_with_vehicle')
        if bad:
            healthy_since=None
            if fault is None:
                fault={'wall_time':time.time(),'stale_or_invalid':bad};event('fault',**fault)
                (folder/'guard_fault.json').write_text(json.dumps(fault,indent=2))
            if now-last_request>1 and client.service_is_ready() and pending is None:
                pending=client.call_async(ChangeOperationMode.Request());last_request=now;event('stop_requested',bad=bad)
        elif fault:
            healthy_since=healthy_since or now
            if now-healthy_since>2:
                event('data_recovered_no_auto_resume')
                path=folder/'guard_fault.json'
                if path.exists():path.rename(folder/('guard_recovered_'+str(time.time_ns())+'.json'))
                fault=None
except (KeyboardInterrupt,ExternalShutdownException):
    pass
finally:
    events.close();node.destroy_node()
    if rclpy.ok():rclpy.shutdown()
