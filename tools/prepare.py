"""Pinned preparation only. Does not start CARLA, containers or a vehicle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[1]

def load(name):return json.loads((ROOT/name).read_text())

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def run(args,**kwargs):return subprocess.run(args,check=True,**kwargs)

def artifact(record,destination):
    name=record['file']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*',name):raise ValueError('Unsafe filename')
    if not re.fullmatch('[0-9a-f]{64}',record['sha256']) or record['bytes']<=0:raise ValueError('Unpinned artifact')
    url=urllib.parse.urlsplit(record['url'])
    if url.scheme!='https' or url.username or url.hostname not in {'github.com','downloads.carlasim.com'}:
        raise ValueError('Unsupported download origin')
    destination=destination.resolve();destination.mkdir(parents=True,exist_ok=True)
    target=destination/name
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file() or target.stat().st_size!=record['bytes'] or digest(target)!=record['sha256']:
            raise ValueError('Existing cache differs; preserved')
        return target
    # No credentials are sent; GitHub public asset redirects require none.
    fd,temp=tempfile.mkstemp(prefix='.download-',dir=destination)
    temporary=Path(temp)
    try:
        size=0
        request=urllib.request.Request(record['url'],headers={'User-Agent':'katech-autoware-sils/0.1'})
        with os.fdopen(fd,'wb') as out, urllib.request.urlopen(request,timeout=60) as response:
            final=urllib.parse.urlsplit(response.geturl())
            if final.scheme!='https':raise ValueError('Refused insecure redirect')
            while block:=response.read(1024*1024):
                size+=len(block)
                if size>record['bytes']:raise ValueError('Oversized artifact')
                out.write(block)
        if size!=record['bytes'] or digest(temporary)!=record['sha256']:raise ValueError('Checksum mismatch')
        os.link(temporary,target)  # Atomic no-overwrite publication, including concurrent fetches.
        return target
    finally:
        temporary.unlink(missing_ok=True)

def clone(url,commit,destination):
    if not re.fullmatch(r'https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?',url):raise ValueError('Unsafe repository URL')
    if not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('Repository not commit-pinned')
    destination.mkdir(parents=True,exist_ok=False)
    run(['git','init',str(destination)])
    run(['git','-C',str(destination),'remote','add','origin',url])
    run(['git','-C',str(destination),'fetch','--depth','1','origin',commit])
    run(['git','-C',str(destination),'checkout','--detach',commit])

def sources(destination):
    import yaml
    lock=load('sources.lock.json')
    if destination.exists():raise ValueError('Use a new source directory; existing path preserved')
    clone(lock['autoware']['url'],lock['autoware']['commit'],destination)
    repos=yaml.safe_load((ROOT/'autoware.repos').read_text())['repositories']
    for name,row in repos.items():
        path=Path(name)
        if path.is_absolute() or '..' in path.parts:raise ValueError('Unsafe repository path')
        clone(row['url'],row['version'],destination/'src'/path)
    patch=lock['local_calibration_patch'];file=ROOT/patch['file']
    if digest(file)!=patch['sha256']:raise ValueError('Calibration patch differs')
    cwd=destination/'src'/patch['repository']
    run(['git','apply','--check',str(file)],cwd=cwd)
    run(['git','apply',str(file)],cwd=cwd)
    stamp={'lock_sha256':digest(ROOT/'sources.lock.json'),'repos_sha256':digest(ROOT/'autoware.repos')}
    (destination/'.sils-prepared.json').write_text(json.dumps(stamp,indent=2)+'\n')

def build_base(destination):
    import yaml
    lock=load('sources.lock.json')
    stamp=json.loads((destination/'.sils-prepared.json').read_text())
    if stamp!={'lock_sha256':digest(ROOT/'sources.lock.json'),'repos_sha256':digest(ROOT/'autoware.repos')}:
        raise ValueError('Source preparation stamp differs')
    pairs=[(destination,lock['autoware']['commit'])]
    pairs += [(destination/'src'/name,row['version']) for name,row in yaml.safe_load((ROOT/'autoware.repos').read_text())['repositories'].items()]
    for path,expected in pairs:
        actual=subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip()
        if actual!=expected:raise ValueError('Source revision changed')
    patch=lock['local_calibration_patch']
    for path,_ in pairs:
        diff=subprocess.check_output(['git','-C',str(path),'diff','--binary','HEAD'])
        untracked=subprocess.check_output(['git','-C',str(path),'ls-files','--others','--exclude-standard'],text=True).splitlines()
        if path==destination/'src'/patch['repository']:
            run(['git','apply','--reverse','--check',str(ROOT/patch['file'])],cwd=path)
            # The committed upstream base has no CARLA calibration files: they are untracked after apply.
            expected_untracked=['individual_params/config/default/carla_sensor_kit/sensor_kit_calibration.yaml',
                                'individual_params/config/default/carla_sensor_kit/sensors_calibration.yaml']
            if diff or sorted(untracked)!=sorted(expected_untracked):raise ValueError('Unexpected calibration changes')
        elif diff or (path!=destination and untracked):raise ValueError('Dirty source repository')
    env=os.environ.copy();env['SKIP_SOURCE_UPDATE']='true'
    run(['bash','partition/partition_build.sh','--repo','katech-autoware-sils-base','--platform','linux/amd64','--carla'],
        cwd=destination,env=env)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['plan','fetch-models','fetch-carla','sources','build-base','build-sils'])
    parser.add_argument('--destination',type=Path)
    args=parser.parse_args()
    if args.action=='plan':
        print(json.dumps({'carla':load('carla.lock.json'),'sources':load('sources.lock.json'),
            'model_files':len(load('models/manifest.json')['files']),
            'full_sils_integration_ready':False,'starts_simulation':False},indent=2));return
    if args.destination is None:parser.error('--destination required')
    destination=args.destination.expanduser().resolve()
    if args.action=='sources':sources(destination)
    elif args.action=='build-base':build_base(destination)
    elif args.action=='build-sils':
        from overlay_sources import verify
        verify(destination)
        env=os.environ.copy();env['SKIP_SOURCE_UPDATE']='true'
        run(['bash','partition/partition_build.sh','--repo','katech-autoware-sils','--platform','linux/amd64','--carla'],cwd=destination,env=env)
    elif args.action=='fetch-models':
        for row in load('models/manifest.json')['files']:print(artifact(row,destination))
    else:
        row=load('carla.lock.json');row['file']='CARLA_0.9.15.tar.gz';print(artifact(row,destination))

if __name__=='__main__':main()
