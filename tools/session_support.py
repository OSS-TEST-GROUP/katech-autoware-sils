"""Validated local-only session identity and filesystem checks."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from container_command import safe_name, directory

GIB=1024**3


def command(args,timeout=30,**kwargs):
    env=os.environ.copy();env.pop('DOCKER_CONTEXT',None);env.pop('DOCKER_HOST',None)
    return subprocess.run(args,check=True,text=True,capture_output=True,timeout=timeout,env=env,**kwargs)


def endpoint(value):
    if not isinstance(value,str) or not value.startswith('unix:///'):raise ValueError('Local Unix Docker socket required')
    directory(value[7:])
    return value


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def save(path,value):
    path=Path(path);temporary=path.with_suffix(path.suffix+'.pending')
    temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(path)


def mount_record(path):
    return json.loads(command(['findmnt','-J','-T',str(path),'-o','SOURCE,TARGET,FSTYPE,OPTIONS,UUID']).stdout)['filesystems'][0]


def check_mount(current,expected):
    if any(current.get(k)!=expected.get(k) for k in ('source','target','fstype','uuid')):
        raise RuntimeError('Filesystem identity changed')
    if current.get('fstype')!='ext4' or 'rw' not in current.get('options','').split(','):
        raise RuntimeError('Writable ext4 filesystem required')


def mount_health(path,expected,min_free):
    current=mount_record(path);check_mount(current,expected)
    device=Path(current['source']).resolve().name
    counter=Path('/sys/fs/ext4')/device/'errors_count'
    if not counter.is_file() or counter.read_text().strip()!='0':raise RuntimeError('Filesystem error or unavailable health counter')
    raid=Path('/sys/class/block')/device/'md/array_state'
    if raid.exists() and raid.read_text().strip() not in ('active','clean','active-idle','write-pending'):
        raise RuntimeError('RAID state not healthy')
    free=shutil.disk_usage(path).free
    if free<min_free:raise RuntimeError('Required free-space reserve reached')
    return free


def validate_descriptor(data):
    if data.get('schema')!=1 or data.get('simulation_only') is not True or data.get('auto_engage') is not False:
        raise ValueError('Explicit non-auto-engaging simulation session required')
    safe_name(data['name']);endpoint(data['docker_host']);endpoint(data['parent_host'])
    for value in data['images'].values():
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',value):raise ValueError('Pinned image ID required')
    if set(data['images'])!={'control','decision','perception'}:raise ValueError('Three native images required')
    if data.get('parent'):
        safe_name(data['parent']['name'])
        if not re.fullmatch(r'[a-f0-9]{64}',data['parent']['id']):raise ValueError('Pinned parent container ID required')
        if not data.get('gpu_driver_dir'):raise ValueError('Nested daemon needs verified driver directory')
        directory(data['gpu_driver_dir'])
    elif data.get('gpu_driver_dir'):raise ValueError('Manual driver bind allowed only in verified local parent')
    for key in ('installation','bundle','stage'):
        directory(data[key])
    if data['map_id']!='ctrack':raise ValueError('A validated runtime profile for this map is not yet available')
    return data


def verify_files(folder,rows):
    folder=Path(folder)
    for row in rows:
        name=row['file']
        if Path(name).name!=name:raise ValueError('Unsafe manifest filename')
        file=folder/name
        if file.is_symlink() or not file.is_file() or digest(file)!=row['sha256']:
            raise ValueError('Input artifact hash mismatch: '+name)
        if 'bytes' in row and file.stat().st_size!=row['bytes']:raise ValueError('Input artifact size mismatch: '+name)


def gpu_identity():
    return command(['nvidia-smi','--query-gpu=name,uuid,driver_version','--format=csv,noheader']).stdout.strip()


def check_owned_volumes(volumes,bundle_id,records):
    if set(volumes)!={'map','data','source','models','engines'} or len(set(volumes.values()))!=5:
        raise ValueError('Five distinct session volumes required')
    if len(records)!=5 or {r['Name'] for r in records}!=set(volumes.values()):
        raise RuntimeError('Session volume identity differs')
    if any((r.get('Labels') or {}).get('katech.sils.bundle')!=bundle_id for r in records):
        raise RuntimeError('Refusing volume not owned by this session')
