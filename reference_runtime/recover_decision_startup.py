"""Republish native operation mode after decision-only restart, while stopped.

The scenario selector may miss the latched state across container restarts.
Use the ordinary LOCAL->STOP API sequence, never autonomous or fake state data.
"""
import os,time
import rclpy
from rclpy.qos import QoSProfile,DurabilityPolicy
from autoware_adapi_v1_msgs.msg import OperationModeState
from nav_msgs.msg import Odometry
from rosidl_runtime_py.utilities import get_service
assert os.environ.get('ROS_DOMAIN_ID')=='222'
rclpy.init();n=rclpy.create_node('ctrack_decision_startup_recovery');state={};receipt={}
def receive(key,msg):state[key]=msg;receipt[key]=time.monotonic()
subscriptions=[n.create_subscription(OperationModeState,'/api/operation_mode/state',lambda m:receive('mode',m),QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL)),
               n.create_subscription(Odometry,'/localization/kinematic_state',lambda m:receive('odom',m),10)]
deadline=time.monotonic()+40;stable=None
while time.monotonic()<deadline:
    rclpy.spin_once(n,timeout_sec=.1)
    ready=any(i.node_name=='scenario_selector' for topic in ['/system/operation_mode/state','/api/operation_mode/state'] for i in n.get_subscriptions_info_by_topic(topic))
    stopped=('mode' in state and state['mode'].mode==1 and 'odom' in state and abs(state['odom'].twist.twist.linear.x)<.05 and time.monotonic()-receipt['odom']<.5)
    stable=(stable or time.monotonic()) if stopped else None
    if ready and stable and time.monotonic()-stable>3:break
else:raise RuntimeError('Decision subscription or fresh stopped state not ready; no mode change performed')
name='/system/operation_mode/change_operation_mode';typ=get_service(dict(n.get_service_names_and_types())[name][0])
c=n.create_client(typ,name);assert c.wait_for_service(timeout_sec=5)
for value in [3,1]:
    req=typ.Request();req.mode=value;f=c.call_async(req);rclpy.spin_until_future_complete(n,f,timeout_sec=10)
    assert f.done() and f.result().status.success,str(f.result())
    end=time.monotonic()+.8
    while time.monotonic()<end:rclpy.spin_once(n,timeout_sec=.05)
assert state['mode'].mode==1
print('Native operation state refreshed; STOP retained. Route and autonomous readiness require separate checks.',flush=True)
n.destroy_node();rclpy.shutdown()
