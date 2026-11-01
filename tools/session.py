"""Initialize and supervise one local CARLA/Autoware session (GUI is opt-in).

Never builds, downloads, repairs storage, modifies a daemon, or engages by default.
All map/profile/results are private. Keep this session bundle outside public Git.
"""
import argparse
import fcntl
import io
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time
import uuid

from prepare import ROOT
from prepare_runtime import prepare, validate as validate_runtime
from container_command import partition_command, safe_name
from gui_support import prepare_gui, check_gui
from session_support import (command, endpoint, digest, save, mount_record, mount_health,
    validate_descriptor, verify_files, gpu_identity, check_owned_volumes, GIB)

OFFICIAL_BINARY='1da989e4ff136e0658fdea421bc1da2b0e5cb018c6e767efc4f6129c21ab1a81'


def docker(host):return ['docker','--host',endpoint(host)]


def info(client):
    raw=json.loads(command(client+['info','--format','{{json .}}']).stdout)
    return dict(id=raw['ID'],name=raw['Name'],root=raw['DockerRootDir'])


def pin_image(client,reference):
    value=json.loads(command(client+['image','inspect',reference]).stdout)[0]
    if value['Architecture']!='amd64' or value['Os']!='linux':raise ValueError('Linux amd64 image required')
    return value['Id']


def initialize(a):
    if os.getuid()!=1000:raise ValueError('Current native image profile requires host uid 1000')
    if a.gui and a.parent:raise ValueError('GUI currently requires a normal host NVIDIA Docker daemon')
    safe_name(a.name);client=docker(a.docker_host);outer=docker(a.parent_host)
    bundle=a.bundle.resolve();installation=a.installation.resolve()
    if bundle.exists() or a.bundle.is_symlink():raise ValueError('New private bundle directory required')
    if ROOT==bundle or ROOT in bundle.parents:raise ValueError('Private bundle cannot be inside public repository')
    if not bundle.parent.is_dir():raise ValueError('Create the chosen runtime parent directory first')
    if bundle.parent.stat().st_dev==installation.stat().st_dev:
        raise ValueError('Runtime logs must be on a different filesystem from bulk installation')
    bulk=mount_record(installation);runtime_mount=mount_record(bundle.parent)
    mount_health(installation,bulk,150*GIB);mount_health(bundle.parent,runtime_mount,20*GIB)
    installed=json.loads((installation/'assets-installation.json').read_text())
    if installed['map_id']!=a.map:raise ValueError('Selected map differs from installed assets')
    if digest(installation/'carla/CarlaUE4/Binaries/Linux/CarlaUE4-Linux-Shipping')!=OFFICIAL_BINARY:
        raise ValueError('Official CARLA executable changed')
    models=json.loads((ROOT/'models/manifest.json').read_text())['files']
    centerpoint=json.loads((ROOT/'models/centerpoint.json').read_text())['files']
    verify_files(a.models,models);verify_files(a.centerpoint,centerpoint)
    engine_report=json.loads((a.engines/'trt_validation.json').read_text())
    engines=engine_report['results']
    if len(engines)!=2 or {e['batch'] for e in engines}!={1,6} or not all(e['passed'] for e in engines):
        raise ValueError('Fresh GPU numerical validation for batch 1 and 6 required')
    for engine in engines:
        expected=next(r for r in models if r['kind']=='classifier' and r['batch']==engine['batch'])
        if engine['onnx_sha256']!=expected['sha256'] or engine['trt_version']!='10.8.0.43':
            raise ValueError('Engine model or native TensorRT version differs')
    verify_files(a.engines,[dict(file=e['engine'],sha256=e['engine_sha256']) for e in engines])
    parent=None;host='127.0.0.1'
    daemon=info(client)
    if a.parent:
        value=json.loads(command(outer+['inspect',a.parent]).stdout)[0]
        if not value['State']['Running'] or daemon['name']!=value['Id'][:12]:raise ValueError('Docker endpoint is not the selected local parent')
        memory=value['HostConfig']['Memory'];cpuset=value['HostConfig']['CpusetCpus']
        if not 24*GIB<=memory<=48*GIB or not cpuset:raise ValueError('Nested parent needs existing bounded memory and CPU affinity')
        host=value['NetworkSettings']['Networks']['bridge']['Gateway']
        parent=dict(name=a.parent,id=value['Id'],memory=memory,cpuset=cpuset)
        outer_store=Path(info(outer)['root'])
        if outer_store.stat().st_dev!=bundle.parent.stat().st_dev:
            raise ValueError('Nested parent runtime and chosen host runtime must use the same independent filesystem')
        if not a.gpu_driver_dir:raise ValueError('Verified parent GPU driver directory required')
        command(outer+['exec',a.parent,'test','-f',a.gpu_driver_dir+'/libcuda.so.1'])
    elif a.docker_host!=a.parent_host:
        raise ValueError('Non-default local endpoint needs explicit verified parent mapping')
    images={k:pin_image(client,getattr(a,k)) for k in ('perception','decision','control')}
    bundle.mkdir(mode=0o700);(bundle/'runs').mkdir()
    gui=prepare_gui(bundle) if a.gui else None
    unique=uuid.uuid4().hex[:12];seed=a.name+'-'+unique+'-seed'
    volumes={k:a.name+'-'+unique+'-'+k for k in ('map','data','source','models','engines')}
    # New uniquely named volumes only; never reuse or overwrite external volumes.
    for key,name in volumes.items():
        if subprocess.run(client+['volume','inspect',name],capture_output=True).returncode==0:
            raise ValueError('New owned volume name is already in use')
        command(client+['volume','create','--label','katech.sils.bundle='+unique,name])
    create=client+['create','--name',seed,'--label','katech.sils.bundle='+unique,'--network','none']
    for key,target in [('map','/autoware_map'),('data','/autoware_data'),('source','/repo'),('models','/models'),('engines','/engines')]:
        create+=['--mount',f'type=volume,src={volumes[key]},dst={target}']
    command(create+['--entrypoint','/bin/true',images['perception']])
    command(client+['cp',seed+':/opt/autoware/share/obigo_launch',str(bundle/'native-share')])
    prepare(installation,bundle/'native-share',bundle/'stage',host,a.port,a.domain,headless=not a.gui)
    for source,target in [(installation/'autoware_map','/autoware_map'),(a.models,'/models')]:
        command(client+['cp',str(source.resolve())+'/.',seed+':'+target],timeout=120)
    command(client+['cp',str(a.centerpoint.resolve()),seed+':/autoware_data/lidar_centerpoint'],timeout=120)
    command(client+['cp',str(a.engines.resolve()),seed+':/engines/classifier'],timeout=120)
    for name in ('ctrack_perception_v2','aihub188_mobilenetv2'):
        command(client+['cp',str(ROOT/name),seed+':/repo/'+name],timeout=60)
    cfg=dict(schema=1,name=a.name,simulation_only=True,auto_engage=False,map_id=a.map,
        bundle=str(bundle),installation=str(installation),stage=str(bundle/'stage'),
        docker_host=a.docker_host,parent_host=a.parent_host,daemon=daemon,parent=parent,
        gpu_driver_dir=a.gpu_driver_dir,images=images,volumes=volumes,seed=seed,bundle_id=unique,
        bulk_mount=bulk,runtime_mount=runtime_mount,gpu=gpu_identity(),models=models,centerpoint=centerpoint,
        engine_report=engine_report,gui=gui,
        map_files=[dict(file=f.name,sha256=digest(f)) for f in (installation/'autoware_map').iterdir() if f.is_file()],
        stage_files={str(f.relative_to(bundle/'stage')):digest(f) for f in (bundle/'stage').rglob('*') if f.is_file()},
        created_wall_time=time.time())
    validate_descriptor(cfg);save(bundle/'session.json',cfg)
    print(json.dumps(dict(session=str(bundle/'session.json'),starts_simulation=False,auto_engage=False),indent=2))


class Session:
    def __init__(self,path):
        self.path=path.resolve();self.cfg=validate_descriptor(json.loads(self.path.read_text()))
        self.bundle=Path(self.cfg['bundle'])
        if self.path!=self.bundle/'session.json':raise ValueError('Session moved; initialize a new bundle')
        self.client=docker(self.cfg['docker_host']);self.outer=docker(self.cfg['parent_host'])
        if info(self.client)!=self.cfg['daemon']:raise RuntimeError('Docker daemon identity changed')
        volume_info=json.loads(command(self.client+['volume','inspect',*self.cfg['volumes'].values()]).stdout)
        check_owned_volumes(self.cfg['volumes'],self.cfg['bundle_id'],volume_info)
        self.parent=self.cfg['parent'];self.stage=Path(self.cfg['stage'])
        if self.parent:
            value=json.loads(command(self.outer+['inspect',self.parent['name']]).stdout)[0]
            if (value['Id']!=self.parent['id'] or not value['State']['Running'] or
                value['HostConfig']['Memory']!=self.parent['memory'] or value['HostConfig']['CpusetCpus']!=self.parent['cpuset']):
                raise RuntimeError('Isolated parent identity/resources changed')
        if gpu_identity()!=self.cfg['gpu']:raise RuntimeError('GPU/driver changed; regenerate engines and initialize again')
        self.settings=validate_runtime(json.loads((self.stage/'config/runtime.json').read_text()))
        self.gui=self.cfg.get('gui')
        if bool(self.gui)==self.settings['headless']:raise ValueError('GUI profile and session differ')
        if self.gui:
            if self.parent:raise ValueError('GUI requires normal host GPU runtime')
            check_gui(self.gui)
        expected_host=value['NetworkSettings']['Networks']['bridge']['Gateway'] if self.parent else '127.0.0.1'
        if self.settings['carla_host']!=expected_host:raise RuntimeError('Runtime bridge target differs from verified local server gateway')
        for name,expected in self.cfg['stage_files'].items():
            if digest(self.stage/name)!=expected:raise RuntimeError('Prepared stage changed; initialize a new session')
        self.ident=self.settings['installation_id'];self.children=[];self.server=None;self.stopping=False
        self.check_storage()

    def check_storage(self):
        return dict(bulk_free_bytes=mount_health(self.cfg['installation'],self.cfg['bulk_mount'],150*GIB),
            runtime_free_bytes=mount_health(self.bundle,self.cfg['runtime_mount'],20*GIB))

    def transport(self,args):
        return self.outer+['exec',self.parent['name'],*args] if self.parent else args

    def heartbeat(self):
        health=self.check_storage()
        used=int(command(self.transport(['du','-sb',str(self.runtime)]),timeout=8).stdout.split()[0])
        if self.parent:used+=sum(p.stat().st_size for p in self.out.rglob('*') if p.is_file())
        if used>=1536*1024**2:raise RuntimeError('Runtime log high-water reached')
        health.update(installation_id=self.ident,wall_time=time.time(),used_bytes=used,pid=os.getpid())
        if self.parent:
            raw=json.dumps(health).encode();stream=io.BytesIO()
            with tarfile.open(fileobj=stream,mode='w') as tar:
                entry=tarfile.TarInfo('guard.pending');entry.size=len(raw);entry.uid=entry.gid=1000;entry.mode=0o644
                tar.addfile(entry,io.BytesIO(raw))
            subprocess.run(self.outer+['cp','-',self.parent['name']+':'+str(self.runtime)],input=stream.getvalue(),capture_output=True,check=True,timeout=8)
            command(self.transport(['mv',str(self.runtime)+'/guard.pending',str(self.runtime)+'/guard.json']))
        else:save(self.runtime/'guard.json',health)
        save(self.out/'host-health.json',health)

    def owned(self,cid):
        data=json.loads(command(self.client+['inspect',cid]).stdout)[0]
        if data['Config']['Labels'].get('katech.sils.role')!=self.label:raise RuntimeError('Container ownership mismatch')
        return data

    def ros(self,action,seconds=3):
        if action not in ('health','goal','start','stop'):raise ValueError('Unsupported native action')
        name=self.names['control'];self.owned(name)
        return command(self.client+['exec',name,'bash','-lc',
            f'source /opt/autoware/setup.bash && python3 /code/inspect_ros.py {action} --seconds {int(seconds)}'],timeout=14)

    def stop_native(self):
        if 'control' not in self.names:return False
        self.owned(self.names['control'])
        result=command(self.client+['exec',self.names['control'],'bash','-lc',
            'source /opt/autoware/setup.bash && python3 /code/emergency_stop.py'],timeout=10)
        return 'STOP acknowledged' in result.stdout

    def verify_volumes(self):
        checks=[]
        for kind,folder,target,rows in [
            ('map',Path(self.cfg['installation'])/'autoware_map','/autoware_map',self.cfg['map_files']),
            ('models',None,'/models',self.cfg['models']),
            ('data',None,'/autoware_data/lidar_centerpoint',self.cfg['centerpoint']),
            ('engines',None,'/engines/classifier',[dict(file=r['engine'],sha256=r['engine_sha256']) for r in self.cfg['engine_report']['results']])]:
            if rows is None:rows=[dict(file=p.name,sha256=digest(p)) for p in folder.iterdir() if p.is_file()]
            volume_target='/autoware_data' if kind=='data' else '/engines' if kind=='engines' else target
            cmd=self.client+['run','--rm','--network','none','--read-only','--user','1000:1000','--cap-drop','ALL',
                '--mount',f'type=volume,src={self.cfg["volumes"][kind]},dst={volume_target},readonly',
                '--entrypoint','/usr/bin/sha256sum',self.cfg['images']['perception']]
            lines=command(cmd+[target+'/'+r['file'] for r in rows],timeout=90).stdout.splitlines()
            if len(lines)!=len(rows) or any(line.split()[0]!=row['sha256'] for line,row in zip(lines,rows)):
                raise RuntimeError('Staged volume integrity mismatch: '+kind)

    def run(self,a):
        import carla
        lock=(self.bundle/'run.lock').open('a')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (self.bundle/'active.json').exists():raise RuntimeError('Previous session still active or needs owned-resource recovery')
        token=uuid.uuid4().hex[:10];self.label=self.cfg['name']+'-'+token
        self.out=self.bundle/'runs'/token;self.out.mkdir()
        self.runtime=Path('/tmp')/self.label if self.parent else self.out/'runtime'
        self.names={};report=dict(startup_passed=False,shutdown_passed=False,auto_engage=False,simulation_only=True)
        self.verify_volumes()
        if int(command(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits']).stdout.strip())<8000:
            raise RuntimeError('At least 8000 MiB free GPU memory required before starting the server')
        if self.parent:
            command(self.transport(['test','!','-e',str(self.runtime)]))
            command(self.transport(['mkdir',str(self.runtime)]))
            command(self.outer+['cp','-a',str(self.stage)+'/.',self.parent['name']+':'+str(self.runtime)],timeout=60)
        else:shutil.copytree(self.stage,self.runtime)
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:setattr(self,'stopping',True))
        self.heartbeat()
        try:
            port=self.settings['carla_port']
            for p in (port,port+1,port+2):
                if command(['ss','-H','-ltnp','sport','=',':'+str(p)]).stdout.strip():raise RuntimeError('Port already in use')
                with socket.socket() as sock:
                    sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);sock.bind(('0.0.0.0',p))
            binary=Path(self.cfg['installation'])/'carla/CarlaUE4/Binaries/Linux/CarlaUE4-Linux-Shipping'
            if digest(binary)!=OFFICIAL_BINARY:raise RuntimeError('CARLA binary changed')
            resource.setrlimit(resource.RLIMIT_CORE,(0,0))
            display_args=['-windowed','-ResX=1280','-ResY=720'] if self.gui else ['-RenderOffScreen','-ResX=640','-ResY=360']
            cmd=[str(binary),'CarlaUE4',*display_args,'-quality-level=Epic',
                f'-carla-rpc-port={port}',f'-carla-streaming-port={port+1}',f'-carla-secondary-port={port+2}',
                '-nosound','-prefernvidia','-ExecCmds=t.MaxFPS 20','-UserDir='+str(self.out/'server_user')]
            with (self.out/'server.log').open('x') as log:
                env=os.environ.copy();env.setdefault('DISPLAY',':1');env.setdefault('XAUTHORITY','/run/user/1000/gdm/Xauthority')
                if self.gui:env.update(DISPLAY=self.gui['display'],XAUTHORITY=self.gui['authority'])
                self.server=subprocess.Popen(cmd,cwd=binary.parents[3],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            save(self.out/'server.json',dict(pid=self.server.pid,command=cmd))
            deadline=time.monotonic()+150
            last_rpc_error=None
            while True:
                self.heartbeat()
                if self.stopping or self.server.poll() is not None:raise RuntimeError('Startup interrupted')
                listeners=command(['ss','-H','-ltnp','sport','=',':'+str(port)]).stdout
                if listeners:
                    if set(re.findall(r'pid=(\d+)',listeners))!={str(self.server.pid)}:raise RuntimeError('RPC listener ownership differs')
                    try:
                        # A CARLA client created before the listener is ready can
                        # retain a failed RPC connection. Retry with a new client.
                        client=carla.Client('127.0.0.1',port);client.set_timeout(5)
                        if client.get_server_version()!='0.9.15':raise ValueError('CARLA version differs')
                        client.get_world().get_map();break
                    except RuntimeError as exc:last_rpc_error=str(exc)
                if time.monotonic()>deadline:raise RuntimeError('CARLA startup timed out: '+str(last_rpc_error))
                time.sleep(1)
            print('CARLA RPC ready; loading selected map',flush=True)
            client.set_timeout(60);world=client.load_world(self.settings['carla_map']);client.set_timeout(5)
            if world.get_map().name.removeprefix('/Game/').lstrip('/')!=self.settings['carla_map'].removeprefix('/Game/').lstrip('/'):
                raise RuntimeError('Selected map was not loaded')
            self.heartbeat()
            print('Selected map loaded; starting native partitions',flush=True)
            for kind in ('control','decision','perception'):
                name=self.label+'-'+kind
                args=partition_command(kind,self.cfg['images'][kind],name,self.label,str(self.runtime),
                    self.cfg['volumes'],self.settings['ros_domain_id'],self.cfg['gpu_driver_dir'],gui=self.gui)
                cid=command(self.client+args).stdout.strip();self.children.append(cid);self.names[kind]=name
            active=dict(label=self.label,run=str(self.out),runtime=str(self.runtime),names=self.names,
                supervisor_pid=os.getpid(),started=time.time())
            save(self.bundle/'active.json',active)
            start=time.monotonic();goal=False;checked=False;trial=False
            while not self.stopping and time.monotonic()-start<a.seconds:
                self.heartbeat()
                if (self.out/'stop.request').exists():
                    report['shutdown_requested']=True;break
                if self.server.poll() is not None:raise RuntimeError('CARLA exited unexpectedly')
                if any(not self.owned(cid)['State']['Running'] for cid in self.children):raise RuntimeError('Native partition exited')
                elapsed=time.monotonic()-start
                if a.check_route and not goal and elapsed>90:
                    state=json.loads(self.ros('health',3).stdout)
                    if state.get('mode',{}).get('mode')!=1 or not state['counts'].get('/localization/pose_estimator/pose_with_covariance'):
                        raise RuntimeError('Fresh NDT and STOP required before route request')
                    self.heartbeat();result=self.ros('goal',3)
                    (self.out/'goal-console.txt').write_text(result.stdout+result.stderr);goal=True
                if not checked and elapsed>180:
                    result=self.ros('health',8);state=json.loads(result.stdout)
                    (self.out/'health-console.txt').write_text(result.stdout+result.stderr)
                    required=['/clock','/localization/kinematic_state','/localization/pose_estimator/pose_with_covariance',
                        '/perception/object_recognition/objects','/perception/traffic_light_recognition/traffic_signals','/api/operation_mode/state']
                    if a.check_route:required+=['/planning/scenario_planning/trajectory','/control/command/control_cmd']
                    if any(not state['counts'].get(t) for t in required) or state.get('mode',{}).get('mode')!=1:
                        raise RuntimeError('Stopped startup health check failed')
                    report.update(startup_passed=True,health=state);checked=True
                    print('READY: stopped runtime health passed; no automatic engagement',flush=True)
                if a.trial and checked and not trial:
                    self.heartbeat();report['explicit_bounded_trial']=self.bounded_trial(client);trial=True
                    break
                if a.check_only and checked:
                    report['check_only_completed']=True;break
                time.sleep(1)
            report['supervisor_signal_received']=self.stopping
        except BaseException as exc:report['error']=repr(exc);print('SESSION ERROR:',repr(exc),flush=True)
        finally:
            try:report['native_stop_acknowledged']=self.stop_native()
            except Exception as exc:report['stop_error']=repr(exc)
            exits=[]
            for cid in self.children:
                try:
                    self.owned(cid)
                    try:self.heartbeat()
                    except Exception:pass
                    command(self.client+['stop','-t','18',cid],timeout=25)
                    data=self.owned(cid)['State'];exits.append(dict(running=data['Running'],exit_code=data['ExitCode'],oom=data['OOMKilled']))
                except Exception as exc:report.setdefault('cleanup_errors',[]).append(repr(exc))
            if self.server and self.server.poll() is None:
                try:
                    raw=Path(f'/proc/{self.server.pid}/cmdline').read_bytes()
                    if str(self.out/'server_user').encode() not in raw:raise RuntimeError('Server ownership differs')
                    self.server.terminate()
                    try:self.server.wait(timeout=12)
                    except subprocess.TimeoutExpired:self.server.kill();self.server.wait(timeout=5)
                except Exception as exc:report.setdefault('cleanup_errors',[]).append(repr(exc))
            report['owned_server_stopped']=self.server is None or self.server.poll() is not None
            report['partition_exit_states']=exits
            report['shutdown_passed']=bool(report['owned_server_stopped'] and report.get('native_stop_acknowledged')
                and len(exits)==3 and all(not e['running'] and e['exit_code']==0 and not e['oom'] for e in exits)
                and not report.get('cleanup_errors'))
            try:
                if self.parent:command(self.outer+['cp',self.parent['name']+':'+str(self.runtime)+'/reports',str(self.out/'container-reports')],timeout=30)
                else:shutil.copytree(self.runtime/'reports',self.out/'container-reports')
            except Exception as exc:report['report_copy_error']=repr(exc)
            save(self.out/'result.json',report)
            save(self.bundle/'last-run.json',dict(run=str(self.out),result=report))
            if (self.bundle/'active.json').exists():(self.bundle/'active.json').rename(self.out/'active-finished.json')
            print(json.dumps(dict(run=str(self.out),startup_passed=report['startup_passed'],shutdown_passed=report['shutdown_passed'],error=report.get('error')),indent=2),flush=True)
            lock.close()
        return 0 if report['startup_passed'] and report['shutdown_passed'] and not report.get('error') else 1

    def bounded_trial(self,client):
        import carla
        world=client.get_world();world.wait_for_tick(5)
        egos=[a for a in world.get_actors().filter('vehicle.*') if a.attributes.get('role_name')=='ego_vehicle']
        if len(egos)!=1:raise RuntimeError('Expected one owned simulator ego')
        ego=egos[0];collisions=[];rows=[];sensor=None;worker=None
        try:
            sensor=world.spawn_actor(world.get_blueprint_library().find('sensor.other.collision'),carla.Transform(),attach_to=ego)
            sensor.listen(lambda e:collisions.append(dict(frame=e.frame,other=e.other_actor.type_id)))
            with (self.out/'trial-console.txt').open('x') as output:
                worker=subprocess.Popen(self.client+['exec',self.names['control'],'bash','-lc',
                    'source /opt/autoware/setup.bash && python3 /code/bounded_drive.py'],stdout=output,stderr=subprocess.STDOUT)
                deadline=time.monotonic()+175
                while worker.poll() is None:
                    self.heartbeat()
                    if self.stopping or (self.out/'stop.request').exists() or time.monotonic()>deadline:raise RuntimeError('Trial interrupted or timed out')
                    if self.server.poll() is not None or any(not self.owned(cid)['State']['Running'] for cid in self.children):raise RuntimeError('Runtime exited during trial')
                    speed=ego.get_velocity().length();rows.append(speed)
                    if collisions or speed>2.2:raise RuntimeError('Collision or physical speed trial guard')
                    time.sleep(.3)
            if worker.returncode!=0 or not rows or rows[-1]>=.05:raise RuntimeError('Native trial/physical STOP failed')
            return dict(passed=True,collision_events=len(collisions),max_physical_speed_mps=max(rows))
        finally:
            if worker and worker.poll() is None:
                try:self.stop_native()
                finally:
                    worker.terminate()
                    try:worker.wait(timeout=3)
                    except subprocess.TimeoutExpired:worker.kill();worker.wait(timeout=3)
            if sensor:
                try:sensor.stop();sensor.destroy()
                except RuntimeError:pass


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    init=sub.add_parser('init')
    for name in ('installation','models','centerpoint','engines','bundle'):init.add_argument('--'+name,type=Path,required=True)
    init.add_argument('--name',required=True);init.add_argument('--map',choices=['ctrack'],required=True)
    init.add_argument('--docker-host',default='unix:///var/run/docker.sock');init.add_argument('--parent-host',default='unix:///var/run/docker.sock')
    init.add_argument('--parent');init.add_argument('--gpu-driver-dir')
    init.add_argument('--gui',action='store_true',help='Opt-in visible CARLA and RViz; local X11 and normal host GPU runtime required')
    init.add_argument('--port',type=int,default=2480);init.add_argument('--domain',type=int,default=222)
    for kind,default in [('perception','perception-runtime'),('decision','adsw-decision-carla'),('control','adsw-control-carla')]:
        init.add_argument('--'+kind,default='katech-autoware-sils:'+default)
    run=sub.add_parser('run');run.add_argument('--session',type=Path,required=True)
    run.add_argument('--seconds',type=int,default=3600);run.add_argument('--check-route',action='store_true')
    run.add_argument('--check-only',action='store_true');run.add_argument('--trial',action='store_true')
    shutdown=sub.add_parser('shutdown');shutdown.add_argument('--session',type=Path,required=True)
    a=p.parse_args()
    if a.action=='init':initialize(a);return 0
    if a.action=='shutdown':
        cfg=validate_descriptor(json.loads(a.session.read_text()));bundle=Path(cfg['bundle'])
        active=json.loads((bundle/'active.json').read_text());run_path=Path(active['run'])
        if run_path.parent!=bundle/'runs':raise ValueError('Invalid active run path')
        (run_path/'stop.request').touch(exist_ok=True)
        print('Shutdown requested; supervisor will request native STOP and stop only its owned processes.');return 0
    if not 200<=a.seconds<=43200:raise ValueError('Run duration must be 200..43200 seconds')
    if a.trial:a.check_route=True
    return Session(a.session).run(a)


if __name__=='__main__':raise SystemExit(main())
