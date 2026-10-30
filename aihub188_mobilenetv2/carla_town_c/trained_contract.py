"""Frozen trained scale_02 contract; no runtime threshold tuning."""
import numpy as np
import onnxruntime as ort
from archive_roi_dataset import letterbox,search_window

def ious(a,boxes):
    b=np.asarray(boxes,dtype=np.float64).reshape(-1,4)
    if not len(b):return np.zeros(0)
    inter=np.maximum(0,np.minimum(a[2:],b[:,2:])-np.maximum(a[:2],b[:,:2])).prod(1)
    area=(a[2]-a[0])*(a[3]-a[1])
    return inter/np.maximum(1e-12,area+np.maximum(0,b[:,2:]-b[:,:2]).prod(1)-inter)

def decode_all(raw):
    assert raw.shape==(3549,8) and np.isfinite(raw).all()
    grids=[];strides=[]
    for stride in (8,16,32):
        yy,xx=np.meshgrid(np.arange(416//stride),np.arange(416//stride),indexing='ij')
        grid=np.stack((xx,yy),axis=-1).reshape(-1,2);grids.append(grid);strides.extend([stride]*len(grid))
    grid=np.concatenate(grids);stride=np.array(strides)[:,None]
    scores=raw[:,4:5]*raw[:,6:8];anchors,classes=np.nonzero(scores>.3)
    if not len(anchors):return []
    centers=(raw[anchors,:2]+grid[anchors])*stride[anchors];sizes=np.exp(raw[anchors,2:4])*stride[anchors]
    boxes=np.concatenate((centers-sizes/2,centers+sizes/2),axis=1);values=scores[anchors,classes]
    order=np.argsort(-values,kind='stable');keep=[]
    while len(order):
        k=int(order[0]);keep.append(k);order=order[1:][ious(boxes[k],boxes[order[1:]])<=.65]
    return [[*boxes[k].tolist(),float(values[k]),int(classes[k])] for k in keep]

def native_select(candidates, expected):
    """Single-target equivalent of native detectionMatch; validated against all 300 ROS boxes."""
    best, best_score = None, np.float32(0)
    a,b,c,d = expected
    width,height = c-a,d-b
    for candidate in candidates:
        x,y,x1,y1 = candidate['box']
        # Unsigned stored offsets are later cast to signed int by calWeightedIou.
        sx,sy = x+(x1-x)//2-width//2,y+(y1-y)//2-height//2
        match, score = None, np.float32(0)
        for det in candidates:
            e,f,g,h = det['box']
            inter = max(min(sx+width,g)-max(sx,e),0)*max(min(sy+height,h)-max(sy,f),0)
            union = width*height+(g-e)*(h-f)-inter
            s = np.float32(np.float32(np.float32(det['score'])*inter)/union) if union else np.float32(0)
            if s >= score:
                score,match = s,det
        if score > best_score:
            best_score,best = score,match
    return best


class TrainedDetector:
    def __init__(self,path):
        options=ort.SessionOptions();options.intra_op_num_threads=4
        self.session=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
        assert self.session.get_inputs()[0].shape==[1,3,416,416]
        assert self.session.get_outputs()[0].shape==[1,3549,8]
    def infer(self,rgb,expected):
        h,w=rgb.shape[:2];window=search_window(expected,w,h)
        x,y,right,bottom=window
        tensor,_,scale=letterbox(rgb[y:bottom,x:right],[])
        raw=self.session.run(None,{self.session.get_inputs()[0].name:tensor[None]})[0][0]
        assert np.isfinite(raw).all() and np.max(np.abs(raw[:,5]))<1e-7
        detections=decode_all(raw);candidates=[]
        for d in detections:
            if d[5]!=0:continue
            a,b,c,e=np.array(d[:4])/scale
            a=int(np.clip(a+x,0,w-2));b=int(np.clip(b+y,0,h-2))
            c=int(np.clip(c+x,a+1,w-1));e=int(np.clip(e+y,b+1,h-1))
            candidates.append({'box':[a,b,c,e],'score':d[4],'class_id':1})
        best=native_select(candidates,expected)
        box=best['box'] if best else [0,0,0,0]
        return {'box':box,'iou':float(ious(expected,[box])[0]),'candidate_count':len(candidates),
                'selected_score':best['score'] if best else None,'window':window}

