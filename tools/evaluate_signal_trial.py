"""Independent post-run signal evaluator; never controls vehicle or perception.

Outputs aggregate metrics only. Inputs/trace contain private map geometry and
must stay private. This does not certify lane-boundary or intersection clearance.
"""
import argparse
import collections
import json
import math
from pathlib import Path


def permits(state, movement):
    if movement not in ('straight','left'):raise ValueError('Unsupported movement')
    return state in (('green','greenleft') if movement=='straight' else ('greenleft','redleft'))


def approach_for(plan, pose):
    p=pose['position'];q=pose['orientation']
    yaw=math.atan2(2*(q['w']*q['z']+q['x']*q['y']),1-2*(q['y']**2+q['z']**2))
    candidates=[]
    for junction in plan['junctions']:
        for a in junction['approaches']:
            hx,hy=a['heading'];sx,sy,*_=a['stop_ros']
            along=(sx-p['x'])*hx+(sy-p['y'])*hy
            lateral=abs((sx-p['x'])*hy-(sy-p['y'])*hx)
            aligned=math.cos(yaw)*hx+math.sin(yaw)*hy
            # A shared signal may cover several parallel lanes. Use the private
            # approach's measured detector corridor, not a single-lane width.
            half_width=a['detector_half_width_m']
            if not math.isfinite(half_width) or not 0<half_width<=20:raise ValueError('Invalid approach corridor')
            if 0<along<100 and lateral<half_width and aligned>.95:candidates.append((along,a))
    if not candidates:raise ValueError('No unambiguous forward signal approach')
    candidates.sort(key=lambda r:r[0])
    if len(candidates)>1 and abs(candidates[0][0]-candidates[1][0])<1:
        raise ValueError('Ambiguous signal approach')
    return candidates[0][1]


def evaluate(rows, approach, movement, front_offset):
    if not 2<=front_offset<=5:raise ValueError('Expected rear-axle to front bumper distance')
    ids=approach['signal_ids']
    if len(ids)!=1:raise ValueError('Single-head evaluation only')
    ident=str(ids[0]);hx,hy=approach['heading'];sx,sy,*_=approach['stop_ros']
    counts=collections.Counter();phases=collections.Counter();stopped_by_phase=collections.Counter();crossings=[];stop_seconds=0.;previous=None
    stale=0;recognition_stale=0
    for row in rows:
        now=row['sim_time'];x,y=row['gt_xy'];speed=abs(row['speed_mps'])
        distance=(sx-x)*hx+(sy-y)*hy-front_offset
        state=row['visual_states'].get(ident,'unknown')
        # CARLA elapsed time and bridge GameTime have different origins.
        # Use the same-host wall clock for visual freshness, not their difference.
        visual_age=row.get('wall_time',math.inf)-row.get('visual_wall_time',-math.inf)
        visual_fresh=0<=visual_age<=1.5
        if not visual_fresh:stale+=1
        phases[state]+=1
        diagnostic=row['recognition']
        recognition_fresh=0<=now-diagnostic.get('source_stamp_ns',0)/1e9<=1.5
        if not recognition_fresh:recognition_stale+=1
        found=[r for r in diagnostic.get('results',[]) if str(r['regulatory_id'])==ident]
        label=found[0]['prediction'].get('label','unknown') if len(found)==1 else 'unknown'
        if visual_fresh and recognition_fresh and distance>=-2:
            counts[state+' -> '+str(label)]+=1
        if previous:
            elapsed=now-previous['time']
            if 0<=elapsed<=1 and distance>=-.2 and speed<.1 and not permits(state,movement) and visual_fresh:
                if previous['stopped_for_signal']:
                    stop_seconds+=elapsed
                    if previous['state']==state:stopped_by_phase[state]+=elapsed
            if previous['distance']>0>=distance:
                crossings.append(dict(visual_state=state,recognized_label=label,
                    permission=permits(state,movement),visual_fresh=visual_fresh,
                    recognition_fresh=recognition_fresh,sample_interval_valid=0<elapsed<=1,
                    speed_mps=speed))
        previous=dict(time=now,distance=distance,state=state,
            stopped_for_signal=(distance>=-.2 and speed<.1 and not permits(state,movement) and visual_fresh))
    legal=bool(crossings) and all(c['permission'] and c['visual_fresh'] and c['sample_interval_valid'] for c in crossings)
    return dict(movement=movement,samples=len(rows),phase_samples=dict(phases),
        classification_counts=dict(counts),crossings=crossings,stopped_on_nonpermissive_seconds=stop_seconds,
        stopped_on_nonpermissive_seconds_by_phase=dict(stopped_by_phase),
        stale_visual_samples=stale,stale_recognition_samples=recognition_stale,
        legal_stopline_crossing_observed=legal,
        stop_then_permitted_crossing_observed=legal and stop_seconds>=2,
        scope='One approach; GT/visual states are evaluation only, no input to recognition/control. Not generalized accuracy or whole-map qualification.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime',type=Path,required=True)
    p.add_argument('--trace',type=Path,required=True)
    p.add_argument('--movement',choices=['straight','left'],required=True)
    p.add_argument('--front-offset',type=float,required=True)
    a=p.parse_args()
    plan=json.loads((a.runtime/'signal_network_v1/plan.json').read_text())
    start=json.loads((a.runtime/'config/start.json').read_text())['initial_pose']
    rows=json.loads(a.trace.read_text())['rows']
    print(json.dumps(evaluate(rows,approach_for(plan,start),a.movement,a.front_offset),indent=2))
