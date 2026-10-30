"""Explicit short simulator-only drive through native APIs; no command injection.

Requires an already accepted route and initialized NDT in STOP. This is a smoke
test, not whole-route or lane-boundary qualification. GT is evaluation only.
"""
import json
import argparse
import math
import time
from pathlib import Path

import rclpy
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
from nav_msgs.msg import Odometry
from geometry_msgs.msg import PoseWithCovarianceStamped
from autoware_planning_msgs.msg import Trajectory
from autoware_adapi_v1_msgs.msg import OperationModeState, RouteState
from autoware_adapi_v1_msgs.srv import ChangeOperationMode
from tier4_planning_msgs.msg import VelocityLimit
from std_msgs.msg import String
from runtime_config import load
from runtime_storage27 import guard_health
from trial_checks import cap_confirmed, motion_problem


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full-route',action='store_true',help='Wait for native ARRIVED instead of 8 m, maximum 300 seconds')
    parser.add_argument('--wait-for-phase',choices=['redleft','green'],help='Test orchestration only: wait in STOP for matching visual and camera-classified phase')
    args=parser.parse_args()
    if args.wait_for_phase and not args.full_route:raise ValueError('Phase wait requires explicit route trial')
    config = load()
    rclpy.init()
    node = rclpy.create_node('fresh_install_bounded_drive')
    node.set_parameters([rclpy.Parameter('use_sim_time', value=True)])
    latest, received, subscriptions = {}, {}, []
    transient = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    live = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
    def receive(key, message):
        latest[key] = message
        received[key] = time.monotonic()
    for key, typ, topic, qos in [
        ('odom', Odometry, '/localization/kinematic_state', live),
        ('ndt', PoseWithCovarianceStamped, '/localization/pose_estimator/pose_with_covariance', live),
        ('gt', PoseWithCovarianceStamped, '/sensing/gnss/pose_with_covariance', live),
        ('trajectory', Trajectory, '/planning/scenario_planning/trajectory', live),
        ('mode', OperationModeState, '/api/operation_mode/state', transient),
        ('route_state', RouteState, '/api/routing/state', transient),
        ('recognition', String, '/ctrack/recognition/diagnostics', live),
        ('limit', VelocityLimit, '/planning/scenario_planning/current_max_velocity', transient)]:
        subscriptions.append(node.create_subscription(typ, topic, lambda m,k=key:receive(k,m), qos))
    publisher = node.create_publisher(VelocityLimit, '/planning/scenario_planning/max_velocity_default', transient)
    report = dict(passed=False, simulator_only=True, cap_kmh=5, requested_distance_m=8,
                  lane_boundary_qualification=False, engaged=False, rows=[])
    goal=json.loads(Path('/results/config/start.json').read_text())['smoke_test_goal']['position']
    report['full_route_requested']=args.full_route
    if args.full_route:report['requested_distance_m']=None
    def spin(seconds):
        end = time.monotonic()+seconds
        while time.monotonic()<end:
            rclpy.spin_once(node, timeout_sec=.03)
    def mode(action):
        client = node.create_client(ChangeOperationMode, '/api/operation_mode/'+action)
        try:
            if not client.wait_for_service(timeout_sec=3):raise RuntimeError('Mode service unavailable: '+action)
            future = client.call_async(ChangeOperationMode.Request())
            rclpy.spin_until_future_complete(node, future, timeout_sec=5)
            if not future.done() or not future.result().status.success:raise RuntimeError('Mode request rejected: '+str(future.result() if future.done() else action))
        finally:node.destroy_client(client)
    def fresh():
        for key in ('odom','ndt','trajectory','gt','recognition'):
            if time.monotonic()-received.get(key,0)>2:raise RuntimeError('Stale required topic: '+key)
        health = guard_health()
        if health is not None:raise RuntimeError('Storage supervisor guard: '+str(health))
    try:
        spin(5)
        fresh()
        state = latest['mode']
        if state.mode!=1 or not state.is_autonomous_mode_available:raise RuntimeError('STOP/autonomous availability precondition failed')
        if abs(latest['odom'].twist.twist.linear.x)>.05:raise RuntimeError('Vehicle is not stopped')
        for _ in range(3):
            message = VelocityLimit();message.stamp=node.get_clock().now().to_msg()
            message.max_velocity=5/3.6;message.sender='ctrack_user';publisher.publish(message);spin(.3)
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            spin(.2);fresh()
            points=latest['trajectory'].points
            if ('limit' in latest and cap_confirmed(latest['limit'].max_velocity,
                (p.longitudinal_velocity_mps for p in points))):break
        else:raise RuntimeError('5 km/h cap not confirmed in trajectory and selected limit')
        if args.wait_for_phase:
            signal_id=str(json.loads(Path('/results/config/private_trial.json').read_text())['signal_id'])
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                spin(.1);fresh()
                if latest['mode'].mode!=1:raise RuntimeError('Phase wait must remain in STOP')
                visual=json.loads(Path('/results/signal_network_v1/live_state.json').read_text())
                results=json.loads(latest['recognition'].data)['results']
                predictions=[r['prediction'].get('label') for r in results if str(r['regulatory_id'])==signal_id]
                if (0<=time.time()-visual['wall_time']<1.5 and visual['states'].get(signal_id)==args.wait_for_phase
                    and predictions==[args.wait_for_phase]):
                    report['engagement_phase']=args.wait_for_phase;break
            else:raise RuntimeError('Requested phase not observed with matching camera classification')
        mode('enable_autoware_control');mode('change_to_autonomous');report['engaged']=True
        start=time.monotonic();last=None;distance=0.;transition_deadline=start+10
        while time.monotonic()-start<(300 if args.full_route else 120):
            spin(.1);fresh()
            state=latest['mode']
            if (state.mode!=2 or state.is_in_transition) and time.monotonic()>transition_deadline:
                raise RuntimeError('Autonomous mode unavailable during trial')
            p=latest['odom'].pose.pose.position;g=latest['gt'].pose.pose.position
            n=latest['ndt'].pose.pose.position
            speed=abs(latest['odom'].twist.twist.linear.x)
            error=math.hypot(p.x-g.x,p.y-g.y)
            problem=motion_problem(speed,error)
            if problem:raise RuntimeError(problem)
            if last:distance+=math.hypot(g.x-last[0],g.y-last[1])
            last=(g.x,g.y)
            visual=json.loads(Path('/results/signal_network_v1/live_state.json').read_text())
            report['rows'].append(dict(wall_time=time.time(),sim_time=node.get_clock().now().nanoseconds/1e9,
                speed_mps=speed,distance_m=distance,gt_xy=[g.x,g.y],
                ekf_gt_xy_m=error,ndt_gt_xy_m=math.hypot(n.x-g.x,n.y-g.y),mode=state.mode,
                visual_states=visual['states'],visual_sim_time=visual['sim_time'],visual_wall_time=visual['wall_time'],
                recognition=json.loads(latest['recognition'].data)))
            if args.full_route and 'route_state' in latest and latest['route_state'].state==RouteState.ARRIVED:
                if math.hypot(p.x-goal['x'],p.y-goal['y'])<2 and speed<.1:
                    report['native_arrived']=True;break
            if not args.full_route and distance>=8:
                report['distance_completed']=True;break
        else:raise RuntimeError('No requested route/distance completion before bounded deadline')
        report['passed']=True
    except BaseException as exc:
        report['error']=repr(exc)
    finally:
        try:
            mode('change_to_stop')
            deadline=time.monotonic()+15;stable=None
            while time.monotonic()<deadline:
                spin(.1)
                valid=(time.monotonic()-received.get('odom',0)<1 and latest['mode'].mode==1
                       and abs(latest['odom'].twist.twist.linear.x)<.05)
                stable=(stable or time.monotonic()) if valid else None
                if stable and time.monotonic()-stable>=2:report['stop_confirmed']=True;break
            if not report.get('stop_confirmed'):raise RuntimeError('STOP did not settle')
        except Exception as exc:
            report['passed']=False;report['stop_error']=repr(exc)
        report['max_speed_mps']=max((r['speed_mps'] for r in report['rows']),default=0)
        report['distance_m']=max((r['distance_m'] for r in report['rows']),default=0)
        report['max_ekf_gt_xy_m']=max((r['ekf_gt_xy_m'] for r in report['rows']),default=0)
        Path('/results/reports/bounded-drive.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k!='rows'}),flush=True)
        node.destroy_node();rclpy.shutdown()
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
