"""Archive-backed ROI preparation, not a drop-in YOLOX trainer or approved data split."""
import io
import math
from pathlib import Path
import numpy as np
from PIL import Image
import cv2

def search_window(box,width,height):
    x0,y0,x1,y1=box;w=x1-x0;h=y1-y0
    return [max(0,x0-w),max(0,y0-h),min(width,x1+w),min(height,y1+h)]

def clipped_objects(objects,window):
    x0,y0,x1,y1=window;out=[]
    for obj in objects:
        a,b,c,d=obj['box'];u=max(a,x0);v=max(b,y0);s=min(c,x1);t=min(d,y1)
        if s<=u or t<=v:continue
        out.append({**obj,'box':[u-x0,v-y0,s-x0,t-y0],
            'visible_fraction':(s-u)*(t-v)/((c-a)*(d-b))})
    return out

def letterbox(rgb,boxes,size=416):
    """Frozen cubic comparison candidate, NOT verified original v3 training transform.

    Integer raster rounding is represented by separate x/y scales for labels;
    exact inverse coordinate conversion is tested. New trainer must adopt this
    contract explicitly or create another version, not mix it with upstream defaults.
    """
    h,w=rgb.shape[:2];scale=min(size/w,size/h)
    rw=max(1,round(w*scale));rh=max(1,round(h*scale))
    bgr=rgb[:,:,::-1].copy();resized=cv2.resize(bgr,(rw,rh),interpolation=cv2.INTER_CUBIC)
    padded=np.full((size,size,3),114,dtype=np.uint8);padded[:rh,:rw]=resized
    xy_scale=np.array([rw/w,rh/h,rw/w,rh/h],dtype=np.float32)
    transformed=np.asarray(boxes,dtype=np.float32).reshape(-1,4)*xy_scale
    return padded.transpose(2,0,1).astype(np.float32),transformed,xy_scale

def decode_source(source):
    assert source['split']=='Training' and source['preparation_only']
    # Never extract archive member paths into the filesystem.
    with open(source['archive'],'rb') as f:f.seek(source['offset']);raw=f.read(source['size'])
    if len(raw)!=source['size']:raise ValueError('truncated_image_bytes')
    with Image.open(io.BytesIO(raw)) as image:rgb=np.asarray(image.convert('RGB'))
    if [rgb.shape[1],rgb.shape[0]]!=source['image_dimensions']:raise ValueError('image_dimensions_mismatch')
    return rgb,raw

class ArchiveRoiDataset:
    def __init__(self,views):self.views=views
    def __len__(self):return len(self.views)
    def __getitem__(self,index):
        view=self.views[index];rgb,_=decode_source(view['source']);x0,y0,x1,y1=view['window']
        crop=rgb[y0:y1,x0:x1]
        objects=clipped_objects(view['source']['objects'],view['window'])
        tensor,boxes,scale=letterbox(crop,[o['box'] for o in objects])
        targets=np.concatenate((boxes,np.array([o['class_id'] for o in objects],dtype=np.float32)[:,None]),axis=1)
        return tensor,targets,{'id':view['id'],'subset':view['subset'],'scale_xyxy':scale,'objects':objects,'crop_size':[x1-x0,y1-y0]}
