"""Opt-in isolated Autoware-compatible recognition node, no planning/control.

Image + CameraInfo + timestamp-matched localization -> static map projection
-> frozen trained YOLOX-S -> guarded C -> native head and group messages.
No subscription to CARLA signal states or evaluator labels.
"""
import argparse,copy,json,time,hashlib,os,signal
from collections import OrderedDict
from pathlib import Path
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.executors import ExternalShutdownException
from sensor_msgs.msg import Image,CameraInfo
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import String
from tier4_perception_msgs.msg import TrafficLight,TrafficLightArray,TrafficLightElement,TrafficLightRoi,TrafficLightRoiArray
from autoware_perception_msgs.msg import TrafficLightGroup,TrafficLightGroupArray,TrafficLightElement as GroupElement
from guarded_pipeline import Pipeline,ROI,unknown
from adapter_core import image_from_message
from trt_backend import TRTBackend
from projector import project,matrix_from_pose

IMAGE='/sensing/camera/camera6/image_raw';INFO='/sensing/camera/camera6/camera_info';POSE='/ctrack/localization/pose'
HEAD='/perception/traffic_light_recognition/camera6/classification/traffic_signals'
GROUP='/perception/traffic_light_recognition/traffic_signals'
EXPECTED='/perception/traffic_light_recognition/camera6/detection/expect/rois'
DETECTED='/perception/traffic_light_recognition/camera6/detection/rois'
DIAG='/ctrack/recognition/diagnostics'
def ns(m):return m.header.stamp.sec*10**9+m.header.stamp.nanosec

class Recognition(Node):
    def __init__(self,args):
        super().__init__('ctrack_guarded_recognition');self.args=args;self.config=json.loads(Path(args.map).read_text());self.signals=self.config['signals'];self.E=self.config['camera']['base_from_camera_flu']
        assert len({s['head_id'] for s in self.signals})==len(self.signals)
        assert len({s['regulatory_id'] for s in self.signals})==len(self.signals),'This single-head adapter cannot fuse multiple heads per group'
        assert hashlib.sha256(Path(args.model).read_bytes()).hexdigest()=='4a66122cc8c364ecc356ff651ddff808f986b6bafa3a109edb126adb4867c962'
        self.backend=TRTBackend(args.engine,require_validated=True);self.pipeline=Pipeline(args.model,self.backend)
        self.caches=[OrderedDict() for _ in range(3)];self.last_stamp=-1;self.last_header=None;self.last_received=0;self.expired=True
        self.head_pub=self.create_publisher(TrafficLightArray,HEAD,10);self.group_pub=self.create_publisher(TrafficLightGroupArray,GROUP,10);self.diag_pub=self.create_publisher(String,DIAG,10)
        self.expected_pub=self.create_publisher(TrafficLightRoiArray,EXPECTED,10);self.detected_pub=self.create_publisher(TrafficLightRoiArray,DETECTED,10)
        for index,(typ,topic) in enumerate([(Image,IMAGE),(CameraInfo,INFO),(PoseStamped,POSE)]):self.create_subscription(typ,topic,lambda m,i=index:self.receive(m,i),10)
        self.create_timer(.05,self.watchdog)
    def all_unknown(self,reason):
        return [{'head_id':s['head_id'],'regulatory_id':s['regulatory_id'],'prediction':unknown(ROI(s['head_id'],0,0,0,0,0),reason)} for s in self.signals]
    def receive(self,message,index):
        key=ns(message);now=self.get_clock().now().nanoseconds
        if key<=0 or key>now+100_000_000 or now-key>self.args.timeout*1e9:
            self.publish(message.header,self.all_unknown('stale_or_future_stamp'),[],0,'stale_or_future_stamp');return
        if key<=self.last_stamp:return
        self.caches[index][key]=(time.monotonic(),message)
        while len(self.caches[index])>8:self.caches[index].popitem(last=False)
        if not all(key in cache for cache in self.caches):return
        image,info,pose=[cache.pop(key)[1] for cache in self.caches];self.last_stamp=key;start=time.monotonic();regions=[];reason=None;details=[]
        try:
            if image.header.frame_id!=self.config['optical_frame'] or info.header.frame_id!=image.header.frame_id or pose.header.frame_id!=self.config['map_frame']:raise ValueError('frame_id_mismatch')
            if image.width!=info.width or image.height!=info.height or any(abs(v)>1e-9 for v in info.d):raise ValueError('camera_info_mismatch_or_unrectified_image')
            p=pose.pose.position;q=pose.pose.orientation;base=matrix_from_pose([p.x,p.y,p.z],[q.x,q.y,q.z,q.w])
            rgb=image_from_message(image);regions,rejected=project(self.signals,base,info.k,info.width,info.height,self.E)
            details=self.pipeline.infer(rgb,regions);present={r['head_id'] for r in details}
            details+= [r for r in self.all_unknown('not_visible_or_invalid_projection') if r['head_id'] not in present]
            if (self.get_clock().now().nanoseconds-key)/1e9>self.args.timeout:raise ValueError('expired_during_processing')
        except Exception as exc:
            reason=str(exc);details=self.all_unknown(reason)
        self.last_header=copy.deepcopy(image.header);self.last_received=time.monotonic();self.expired=False
        self.publish(image.header,details,regions,(time.monotonic()-start)*1000,reason)
        for cache in self.caches:
            for old in list(cache):
                if old<=key:cache.pop(old)
    def publish(self,header,details,regions,elapsed,reason):
        source_key=header.stamp.sec*10**9+header.stamp.nanosec
        header=copy.deepcopy(header);header.frame_id=self.config['optical_frame']
        # Fault notifications are fresh unknowns, not future-dated messages or
        # duplicates of the last green stamp. Preserve source time in diagnostics.
        if reason is not None:header.stamp=self.get_clock().now().to_msg()
        head=TrafficLightArray();head.header=copy.deepcopy(header);group=TrafficLightGroupArray();group.stamp=copy.deepcopy(header.stamp)
        for r in details:
            h=TrafficLight();h.traffic_light_id=int(r['head_id']);h.traffic_light_type=0
            g=TrafficLightGroup();g.traffic_light_group_id=int(r['regulatory_id'])
            for val in r['prediction']['elements']:
                el=TrafficLightElement()
                for k,v in val.items():setattr(el,k,v)
                h.elements.append(el)
                ge=GroupElement();ge.color={1:1,2:2,3:3}.get(val['color'],0);ge.shape={5:1,6:2}.get(val['shape'],0);ge.status=2 if val['status']==16 else 0;ge.confidence=float(val['confidence']);g.elements.append(ge)
            head.signals.append(h);group.traffic_light_groups.append(g)
        self.head_pub.publish(head);self.group_pub.publish(group)
        for publisher,detected in [(self.expected_pub,False),(self.detected_pub,True)]:
            arr=TrafficLightRoiArray();arr.header=copy.deepcopy(header)
            for r in details:
                box=r.get('detector',{}).get('box') if detected else r.get('box')
                if not box:continue
                x,y,c,d=box;rr=TrafficLightRoi();rr.traffic_light_id=r['head_id'];rr.traffic_light_type=0;rr.roi.x_offset=x;rr.roi.y_offset=y;rr.roi.width=c-x;rr.roi.height=d-y;arr.rois.append(rr)
            publisher.publish(arr)
        msg=String();msg.data=json.dumps({'stamp_ns':header.stamp.sec*10**9+header.stamp.nanosec,'source_stamp_ns':source_key,'reason':reason,'processing_ms':elapsed,'results':details,'test_only':True});self.diag_pub.publish(msg)
    def watchdog(self):
        now=time.monotonic()
        for index,cache in enumerate(self.caches):
            for key,(arrival,m) in list(cache.items()):
                if now-arrival>self.args.timeout:
                    cache.pop(key)
                    if index==0:self.publish(m.header,self.all_unknown('missing_matching_camera_info_or_pose'),[],0,'missing_matching_camera_info_or_pose')
        if self.last_header is not None and not self.expired and now-self.last_received>self.args.timeout:
            self.publish(self.last_header,self.all_unknown('input_timeout'),[],0,'input_timeout');self.expired=True

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--enable-test',action='store_true');parser.add_argument('--map',default='/experiment/config/signal_map.json');parser.add_argument('--model',default='/work/yolox_training_v1/scale_02/export/korean_tl_yolox_s_pilot_batch_1.onnx');parser.add_argument('--engine',default='/artifacts/mobilenetv2_batch_6_fp32.engine');parser.add_argument('--timeout',type=float,default=1.)
    args,ros=parser.parse_known_args()
    assert args.enable_test and os.environ.get('ROS_DOMAIN_ID')=='222','Opt-in isolated DDS domain 222 is required'
    assert .1<=args.timeout<=5
    rclpy.init(args=ros);node=None
    try:node=Recognition(args);rclpy.spin(node)
    except (KeyboardInterrupt,ExternalShutdownException):pass
    finally:
        signal.signal(signal.SIGINT,signal.SIG_IGN)
        if node:node.backend.close();node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
if __name__=='__main__':main()
