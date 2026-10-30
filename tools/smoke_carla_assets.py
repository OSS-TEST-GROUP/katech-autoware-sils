"""Bounded independent CARLA asset test. No ROS, driving, or existing-world access."""
import argparse
import json
import os
from pathlib import Path
import queue
import re
import resource
import signal
import socket
import subprocess
import sys
import time
from prepare import digest


def save(path,data):path.write_text(json.dumps(data,indent=2)+'\n')


def health(installation):
    m=json.loads(subprocess.check_output(['findmnt','-J','-T',str(installation),'-o','SOURCE,FSTYPE,OPTIONS']))['filesystems'][0]
    if 'rw' not in m['options'].split(','):raise RuntimeError('Installation filesystem is read-only')
    if m['fstype']=='ext4':
        path=Path('/sys/fs/ext4')/Path(m['source']).resolve().name/'errors_count'
        if path.read_text().strip()!='0':raise RuntimeError('Filesystem errors detected')


def probe(a):
    import carla
    owner=json.loads((a.output/'owned-server.json').read_text())
    pid=int(owner['pid'])
    expected_binary=str(a.installation/'carla/CarlaUE4/Binaries/Linux/CarlaUE4-Linux-Shipping')
    command=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
    if expected_binary.encode() not in command or ('-UserDir='+str(a.output/'user')).encode() not in command:
        raise ValueError('Probe server ownership mismatch')
    expected=json.loads((a.installation/'assets-installation.json').read_text())['carla_map']
    deadline=time.monotonic()+150
    while True:
        try:
            listeners=subprocess.check_output(['ss','-H','-ltnp','sport','=',':'+str(a.port)],text=True)
            pids=set(re.findall(r'pid=(\d+)',listeners))
            if listeners and pids!={str(pid)}:raise ValueError('Port belongs to a different server; no world access allowed')
            if not listeners:raise RuntimeError('Owned server not listening yet')
            client=carla.Client('127.0.0.1',a.port,2);client.set_timeout(5)
            version=client.get_server_version();world=client.get_world();break
        except RuntimeError:
            if time.monotonic()>deadline:raise
            time.sleep(2)
    if version!='0.9.15':raise ValueError('Unexpected server version')
    client.set_timeout(60)
    if world.get_map().name.removeprefix('/Game/').lstrip('/')!=expected.removeprefix('/Game/'):
        world=client.load_world(expected)
    actual=world.get_map()
    if actual.name.removeprefix('/Game/').lstrip('/')!=expected.removeprefix('/Game/'):raise ValueError('Wrong map')
    report=dict(server_version=version,client_version=client.get_client_version(),map=actual.name,
                waypoints=len(actual.generate_waypoints(5)),topology_edges=len(actual.get_topology()),
                states=[],supports=0,heads=0,camera_frames=[],passed=False,driving_test=False)
    if not report['waypoints'] or not report['topology_edges']:raise ValueError('Road topology empty')
    config=a.installation/'profile/sils_map_config'
    placements=json.loads((config/'placements.json').read_text())
    settings=world.get_settings();settings.synchronous_mode=True;settings.fixed_delta_seconds=.05;world.apply_settings(settings)
    world.set_weather(carla.WeatherParameters.ClearNoon);owned=[];camera=None
    try:
        lib=world.get_blueprint_library();mesh=lib.find('static.prop.mesh')
        first=placements[0];position=carla.Location(*first['head_carla'])
        def spawn(name,namespace,placement):
            mesh.set_attribute('mesh_path',f'/Game/{namespace}/{name}.{name}')
            mesh.set_attribute('mass','0');mesh.set_attribute('role_name','sils_asset_test')
            actor=world.spawn_actor(mesh,carla.Transform(carla.Location(*placement['head_carla']),carla.Rotation(yaw=placement['yaw_deg'])))
            owned.append(actor);world.tick();e=actor.bounding_box.extent
            if max(e.x,e.y,e.z)<.1:raise ValueError('Asset did not load: '+name)
            return actor
        for state in ['red','yellow','green','redleft','greenleft','off']:
            actor=spawn('SM_KR_'+state,'KoreanSignalAddonV4',first)
            report['states'].append(state);actor.destroy();owned.remove(actor)
        for p in placements:
            spawn('SM_Support_'+str(p.get('support_template_id',p['regulatory_id'])),'KoreanRoadsideSupportsV2',p);report['supports']+=1
            spawn('SM_KR_red','KoreanSignalAddonV4',p);report['heads']+=1
        bp=lib.find('sensor.camera.rgb')
        for key,value in {'image_size_x':'960','image_size_y':'540','fov':'90','sensor_tick':'0.0'}.items():bp.set_attribute(key,value)
        camera=world.spawn_actor(bp,carla.Transform(carla.Location(x=position.x-35,y=position.y,z=position.z+20),carla.Rotation(pitch=-25,yaw=0)))
        owned.append(camera);frames=queue.Queue();camera.listen(frames.put)
        for i in range(15):
            frame=world.tick();deadline=time.monotonic()+15
            while True:
                image=frames.get(timeout=max(.1,deadline-time.monotonic()))
                if image.frame>=frame:break
            if i in (9,14):
                name=f'overview_{i}.png';image.save_to_disk(str(a.output/name));report['camera_frames'].append(name)
        report['passed']=True
    finally:
        if camera:
            try:camera.stop()
            except RuntimeError:pass
        for actor in reversed(owned):
            try:actor.destroy()
            except RuntimeError:pass
        settings.synchronous_mode=False;world.apply_settings(settings)
        save(a.output/'probe.json',report)


def run(a):
    health(a.installation)
    if not 2403<=a.port<=60000:raise ValueError('Use an isolated port above the original 2400-2402')
    for port in range(a.port,a.port+3):
        with socket.socket() as sock:sock.bind(('127.0.0.1',port))
    memory=subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True)
    if int(memory.strip())<6000:raise ValueError('At least 6 GB GPU headroom required; existing simulation preserved')
    a.output.mkdir(parents=True,exist_ok=False)
    binary=a.installation/'carla/CarlaUE4/Binaries/Linux/CarlaUE4-Linux-Shipping'
    expected='1da989e4ff136e0658fdea421bc1da2b0e5cb018c6e767efc4f6129c21ab1a81'
    if digest(binary)!=expected:raise ValueError('Unexpected official CARLA executable')
    manifest=json.loads((a.installation/'assets-installation.json').read_text())
    cmd=[str(binary),'CarlaUE4',manifest['carla_map'],'-RenderOffScreen','-ResX=640','-ResY=360',
         '-quality-level=Low',f'-carla-rpc-port={a.port}',f'-carla-streaming-port={a.port+1}',
         f'-carla-secondary-port={a.port+2}','-nosound','-prefernvidia','-ExecCmds=t.MaxFPS 10',
         '-UserDir='+str(a.output/'user'),'-AbsLog='+str(a.output/'unreal.log')]
    before=subprocess.check_output(['docker','ps','--format','{{.ID}} {{.Names}}'],text=True)
    env=os.environ.copy();env.setdefault('DISPLAY',':1');env.setdefault('XAUTHORITY','/run/user/1000/gdm/Xauthority')
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));server=None;child=None
    report={'passed':False,'driving_test':False,'port':a.port,'existing_containers_unchanged':False,
            'probe_source_sha256':digest(Path(__file__)),'official_binary_sha256':expected}
    try:
        with (a.output/'server.log').open('x') as log,(a.output/'client.log').open('x') as clientlog:
            server=subprocess.Popen(cmd,cwd=a.installation/'carla',env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            save(a.output/'owned-server.json',dict(pid=server.pid,command=cmd))
            child=subprocess.Popen([sys.executable,__file__,'probe','--installation',str(a.installation),'--output',str(a.output),'--port',str(a.port)],env=env,stdout=clientlog,stderr=subprocess.STDOUT,start_new_session=True)
            deadline=time.monotonic()+210
            while child.poll() is None:
                if server.poll() is not None:raise RuntimeError('Test server exited')
                if time.monotonic()>deadline:raise TimeoutError('Bounded test timed out')
                used=int(subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip())
                if used>15000:raise RuntimeError('GPU headroom limit reached; stop test only')
                health(a.installation);time.sleep(2)
            report['passed']=child.returncode==0 and json.loads((a.output/'probe.json').read_text())['passed']
            report['client_exit']=child.returncode
    except Exception as exc:report['error']=str(exc)
    finally:
        for process in [child,server]:
            if process and process.poll() is None:
                os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=10)
        after=subprocess.check_output(['docker','ps','--format','{{.ID}} {{.Names}}'],text=True)
        report['existing_containers_unchanged']=before==after
        report['test_server_stopped']=server is None or server.poll() is not None
        report['passed']=report['passed'] and report['existing_containers_unchanged'] and report['test_server_stopped']
        save(a.output/'run-result.json',report)
    print(json.dumps(report,indent=2));return 0 if report['passed'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['run','probe'])
    p.add_argument('--installation',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--port',type=int,default=2480)
    a=p.parse_args();a.installation=a.installation.resolve();a.output=a.output.resolve()
    if a.action=='run':raise SystemExit(run(a))
    probe(a)
