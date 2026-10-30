"""Static map + CameraInfo intrinsics + map->base pose + camera extrinsic only.
No CARLA actor, state, dynamic box or image target location enters projection.
ROS map/base use right-handed FLU; optical camera uses right/down/forward.
"""
import numpy as np
FLU_FROM_OPTICAL=np.array([[0,0,1,0],[-1,0,0,0],[0,-1,0,0],[0,0,0,1]],float)
FLIP_Y=np.diag([1,-1,1,1])
def ros_pose(carla_matrix):return FLIP_Y@np.asarray(carla_matrix)@FLIP_Y
def matrix_from_pose(position,quaternion):
    x,y,z,w=quaternion;n=x*x+y*y+z*z+w*w
    if not .99<n<1.01:raise ValueError('invalid_quaternion')
    q=np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
    t=np.eye(4);t[:3,:3]=q;t[:3,3]=position;return t
def quaternion_from_matrix(m):
    # Stable eigen formulation; scalar-last ROS convention.
    r=np.asarray(m)[:3,:3];k=np.array([[r[0,0]-r[1,1]-r[2,2],r[1,0]+r[0,1],r[2,0]+r[0,2],r[2,1]-r[1,2]],
        [r[1,0]+r[0,1],r[1,1]-r[0,0]-r[2,2],r[2,1]+r[1,2],r[0,2]-r[2,0]],
        [r[2,0]+r[0,2],r[2,1]+r[1,2],r[2,2]-r[0,0]-r[1,1],r[1,0]-r[0,1]],
        [r[2,1]-r[1,2],r[0,2]-r[2,0],r[1,0]-r[0,1],np.trace(r)]])/3
    _,v=np.linalg.eigh(k);q=v[:,-1];return q if q[3]>=0 else -q
def project(signals,base_pose,K,width,height,extrinsic):
    pose=np.asarray(base_pose);K=np.asarray(K).reshape(3,3);E=np.asarray(extrinsic)
    if not all(np.isfinite(x).all() for x in [pose,K,E]):raise ValueError('nonfinite_calibration')
    if width<=0 or height<=0 or K[0,0]<=0 or K[1,1]<=0:raise ValueError('invalid_calibration')
    camera=pose@E@FLU_FROM_OPTICAL;inverse=np.linalg.inv(camera);regions=[];rejected=[]
    for s in signals:
        points=np.asarray(s['corners_ros']);center=points.mean(0);to_camera=camera[:3,3]-center;dist=np.linalg.norm(to_camera)
        if dist>100 or dist<2 or np.dot(to_camera,np.asarray(s['front_normal_ros']))/max(dist,1e-6)<.5:continue
        optical=(inverse@np.c_[points,np.ones(len(points))].T).T[:,:3]
        if np.any(optical[:,2]<.1):continue
        pixels=(K@optical.T).T;pixels=pixels[:,:2]/pixels[:,2,None]
        a,b=np.floor(pixels.min(0)).astype(int);c,d=np.ceil(pixels.max(0)).astype(int)
        record={'head_id':s['head_id'],'regulatory_id':s['regulatory_id'],'lanelet_ids':s['lanelet_ids'],'box':[int(a),int(b),int(c),int(d)],'distance_m':float(dist)}
        if a<0 or b<0 or c>=width or d>=height or c-a<8 or d-b<4:
            rejected.append({**record,'reason':'clipped_or_too_small'});continue
        regions.append(record)
    return regions,rejected
