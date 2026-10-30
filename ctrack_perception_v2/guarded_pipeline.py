"""Opt-in four-horizontal-lamp C-Track candidate. Never uses commanded states.

Image evidence only VETOES classifications; it never manufactures a green/red.
Map geometry must be calibrated. Not a generic real-road safety guarantee.
"""
import sys
from pathlib import Path
import numpy as np
BASE=Path('/work') if Path('/work/candidate_c').exists() else Path(__file__).resolve().parents[1]/'aihub188_mobilenetv2'
sys.path[:0]=[str(BASE/'candidate_c'),str(BASE/'carla_town_c'),str(BASE)]
from adapter_core import ROI,classify,unknown
from trained_contract import TrainedDetector,ious

POLICY={'name':'ctrack_horizontal_v1','confidence':.8,'margin':.2,'detector_map_min_iou':.3,
        'evidence_min_value':150,'evidence_min_saturation':.25,'evidence_min_pixels':2,
        'scope':'Only calibrated synthetic horizontal signal heads; off -> unknown, no off class added'}

def evidence(rgb,box):
    x,y,r,b=map(int,box);crop=rgb[y:b,x:r];h,w=crop.shape[:2]
    if h<4 or w<8:return {'pixels':0,'sufficient':False}
    # Ignore surrounding background and housing edges; no temporal/GT state input.
    inner=crop[int(.2*h):max(int(.8*h),int(.2*h)+1),int(.07*w):max(int(.93*w),int(.07*w)+1)].astype(float)
    hi=inner.max(2);lo=inner.min(2);mask=(hi>=150)&((hi-lo)/np.maximum(hi,1)>=.25)
    count=int(mask.sum());return {'pixels':count,'sufficient':count>=2}

def guarded_classify(rgb,expected,detected,backend,identifier=0):
    x,y,r,b=map(int,expected);roi=ROI(int(identifier),0,x,y,r-x,b-y)
    match=float(ious(np.asarray(expected),[detected])[0]);ev=evidence(rgb,expected)
    if match<.3:result=unknown(roi,'detector_map_disagreement')
    elif not ev['sufficient']:result=unknown(roi,'no_visible_lamp_evidence')
    else:result=classify(rgb,[roi],backend)[0]
    return {'prediction':result,'map_detector_iou':match,'lamp_evidence':ev,'classification_box':list(map(int,expected))}

class Pipeline:
    def __init__(self,model,backend):self.detector=TrainedDetector(model);self.backend=backend
    def infer(self,rgb,regions):
        rows=[]
        for r in regions:
            det=self.detector.infer(rgb,r['box']);result=guarded_classify(rgb,r['box'],det['box'],self.backend,r['head_id'])
            rows.append({**r,'detector':det,**result})
        return rows
