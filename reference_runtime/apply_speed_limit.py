"""Verify loaded planning caps and publish the requested cap. Never engages driving."""
import json, time
from pathlib import Path
import rclpy
from rclpy.qos import QoSProfile, DurabilityPolicy
from tier4_planning_msgs.msg import VelocityLimit
from rcl_interfaces.srv import GetParameters

requested=json.loads(Path('/results/config/speed_limit.json').read_text())['requested_kmh']
assert 0 < requested <= 50
target=requested/3.6
rclpy.init()
n=rclpy.create_node('ctrack_requested_speed_limit')
n.set_parameters([rclpy.Parameter('use_sim_time',value=True)])
q=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL)
pub=n.create_publisher(VelocityLimit,'/planning/scenario_planning/max_velocity_default',q)
state={}; subs=[]
for topic in ['/planning/scenario_planning/max_velocity','/planning/scenario_planning/current_max_velocity']:
    subs.append(n.create_subscription(VelocityLimit,topic,lambda m,t=topic:state.update({t:m.max_velocity}),q if topic.endswith('current_max_velocity') else 10))
def spin(seconds):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:rclpy.spin_once(n,timeout_sec=.05)
params={}
for node in ['/planning/scenario_planning/velocity_smoother','/planning/scenario_planning/external_velocity_limit_selector','/planning/scenario_planning/lane_driving/behavior_planning/behavior_path_planner']:
    c=n.create_client(GetParameters,node+'/get_parameters')
    assert c.wait_for_service(timeout_sec=30),node
    req=GetParameters.Request();req.names=['max_vel']
    f=c.call_async(req);rclpy.spin_until_future_complete(n,f,timeout_sec=10)
    assert f.done() and f.result(),node
    value=f.result().values[0].double_value
    assert abs(value-target)<1e-6,(node,value,target)
    params[node]=value
spin(1)
for _ in range(3):
    msg=VelocityLimit();msg.stamp=n.get_clock().now().to_msg()
    msg.max_velocity=target;msg.sender='ctrack_user';pub.publish(msg);spin(.5)
spin(2)
assert len(state)==2 and all(abs(v-target)<1e-6 for v in state.values()),state
report={'requested_kmh':requested,'parameters_mps':params,'published_limits_mps':state,'never_engaged_driving':True}
Path('/results/reports/speed_limit_applied.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
n.destroy_node();rclpy.shutdown()
