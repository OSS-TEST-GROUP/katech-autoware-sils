"""11 physical visual signals, isolated intersection clocks and virtual detectors.

Only the bridge ticks CARLA. This process never publishes recognition or commands
to drive. On any failure it requests STOP and attempts to leave all heads red.
"""
import carla, time, json, math, signal, subprocess, sys, traceback
from pathlib import Path
from signals import SignalScene, ASSET, SUPPORT_ASSET
from signal_scheduler import Network
from signal_detectors import detect
from simulation_lock import scene_transaction
from chase_camera import SmoothChaseCamera
from signal_pool import PooledSignals
from scene_lifecycle import wait_scene_tick

ROOT=Path('/results'); DIR=ROOT/'signal_network_v1'
running=True
def stop(*_):
    global running
    running=False

class NetworkScene(PooledSignals,SignalScene):
    def set_state(self,p,state):
        with scene_transaction():
            return super().set_state(p,state)

    def destroy(self):
        with scene_transaction():
            return super().destroy()

    def mesh(self,name,pose,role,scale=1.,asset=None):
        bp=self.world.get_blueprint_library().find('static.prop.mesh')
        # CARLA's StaticMeshFactory only sets Movable mobility for positive mass.
        # Immediately disable physics again: phase heads are kinematic visuals.
        movable=name.startswith('SM_KR_')
        for k,v in [('mesh_path',f'{asset or ASSET}/{name}.{name}'),('mass','1' if movable else '0'),('scale',str(scale)),('role_name',role)]:
            bp.set_attribute(k,v)
        with scene_transaction():
            a=self.world.spawn_actor(bp,pose)
            if movable:
                a.set_simulate_physics(False)
                a.set_enable_gravity(False)
            if max(a.bounding_box.extent.x,a.bounding_box.extent.y,a.bounding_box.extent.z)>.1:
                return a
            # Never wait for a tick while owning the tick exclusion lock.
            a.destroy()
        raise RuntimeError('Mesh load failed: '+name)

    def deploy(self):
        for p in self.placements:
            self.set_state(p,'red')
            template=p.get('support_template_id',p['regulatory_id'])
            self.supports.append(self.mesh('SM_Support_'+template,self.pose(p),
                'kr_support_'+p['regulatory_id'],asset=SUPPORT_ASSET))

    def fail_red(self):
        errors=[]
        for p in self.placements:
            try:
                if self.states.get(p['regulatory_id'])!='red' or p['regulatory_id'] not in self.heads:
                    self.set_state(p,'red')
            except Exception as exc: errors.append(str(exc))
        return errors

def atomic(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2));tmp.replace(path)

def main():
    global running
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    plan=json.loads((DIR/'plan.json').read_text())
    placements=json.loads(Path('/placements.json').read_text())
    recognition=json.loads((ROOT/'config/signal_map.json').read_text())
    ids=[p['regulatory_id'] for p in placements]
    assert len(ids)==11 and len(set(ids))==11
    assert set(ids)=={i for j in plan['junctions'] for a in j['approaches'] for i in a['signal_ids']}
    assert set(ids)=={str(s['regulatory_id']) for s in recognition['signals']}
    c=carla.Client('127.0.0.1',2400);c.set_timeout(10)
    deadline=time.monotonic()+150;ego=None
    while running and time.monotonic()<deadline:
        world=c.get_world()
        ego=next((a for a in world.get_actors().filter('vehicle.*') if a.attributes.get('role_name')=='ego_vehicle'),None)
        if ego and world.get_settings().synchronous_mode:break
        time.sleep(1)
    assert ego is not None,'No ego vehicle'
    assert world.get_map().name.endswith('/C_track_1_0_7')
    owned=[a for a in world.get_actors().filter('static.prop.mesh') if a.attributes.get('role_name','').startswith(('kr_signal_','kr_support_'))]
    assert not owned,'Old signal scene still owns actors; refuse duplicate controllers'
    scene=NetworkScene(world,placements);fault=False
    camera=SmoothChaseCamera(ego.id)
    events=(DIR/('events_'+str(time.time_ns())+'.jsonl')).open('w',buffering=1)
    try:
        scene.deploy()
        camera.start()
        net=Network(plan,world.get_snapshot().timestamp.elapsed_seconds)
        previous=None;last_report=-1.;last_frame=None;last_progress=time.monotonic()
        while running:
            snap=wait_scene_tick(world,lambda:running)
            if snap is None:break
            now=snap.timestamp.elapsed_seconds
            if last_frame != snap.frame:
                last_progress=time.monotonic();last_frame=snap.frame
            if time.monotonic()-last_progress>10:raise RuntimeError('CARLA clock stalled')
            actors=[]
            for actor in world.get_actors():
                if not actor.type_id.startswith(('vehicle.','walker.pedestrian.')):continue
                tr=actor.get_transform();fv=tr.get_forward_vector()
                actors.append(dict(id=actor.id,xy=[tr.location.x,-tr.location.y],forward=[fv.x,-fv.y],
                    radius=math.hypot(actor.bounding_box.extent.x,actor.bounding_box.extent.y),
                    kind='vehicle' if actor.type_id.startswith('vehicle.') else 'walker'))
            demands,occupied,details=detect(plan,actors)
            states=net.update(now,demands,occupied)
            # Remove permissions first. Across separate RPCs a frame can see all-red,
            # but cannot see a new conflicting green before the old green is removed.
            changed=[p for p in placements if scene.states[p['regulatory_id']]!=states[p['regulatory_id']]]
            changed.sort(key=lambda p: states[p['regulatory_id']] in ('green','greenleft','redleft'))
            for p in changed: scene.set_state(p,states[p['regulatory_id']])
            state={'sim_time':now,'wall_time':time.time(),'states':dict(scene.states),
                   'junctions':net.status(),'detectors':details,'ego_id':ego.id,
                   'visual_actor_pool':True,'active_head_ids':{k:a.id for k,a in scene.heads.items()}}
            signature=(dict(states),sorted(demands),sorted(occupied))
            if signature!=previous:
                events.write(json.dumps(state)+'\n');previous=signature
                print(json.dumps(state),flush=True)
            if now-last_report>=1 or now<last_report:
                atomic(DIR/'live_state.json',state);last_report=now
    except BaseException as exc:
        fault=True
        # Request STOP before potentially blocked CARLA cleanup RPCs.
        # A failed simulator must not delay the independent ROS safety request.
        record={'wall_time':time.time(),'error':repr(exc),'traceback':traceback.format_exc()}
        atomic(DIR/'fault.json',record)
        try:subprocess.run([sys.executable,'/code/emergency_stop.py'],check=True,timeout=10)
        except Exception as stop_error: print('STOP failed:',stop_error,flush=True)
        c.set_timeout(2)
        record['red_errors']=scene.fail_red()
        atomic(DIR/'fault.json',record)
        raise
    finally:
        if camera.thread.ident is not None: camera.close()
        events.close()
        if not fault: scene.destroy()

if __name__=='__main__':main()
