"""Authenticated private Release fetch. Credentials never follow asset redirects."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from prepare import ROOT, digest

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def credential():
    value=os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if value:return value
    env=os.environ.copy();env['GIT_TERMINAL_PROMPT']='0'
    result=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',
                          env=env,text=True,capture_output=True,timeout=15)
    if result.returncode:raise ValueError('GitHub credential unavailable; configure a credential helper or GH_TOKEN')
    fields=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    if not fields.get('password'):raise ValueError('GitHub credential unavailable')
    return fields['password']

class PrivateRelease:
    def __init__(self,repository):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):raise ValueError('Unsafe repository')
        self.repository=repository;self.key=credential()
        self.opener=urllib.request.build_opener(NoRedirect)

    def request(self,path,accept='application/vnd.github+json'):
        if not path.startswith('/repos/'+self.repository+'/') and path!='/repos/'+self.repository:
            raise ValueError('Unexpected API path')
        request=urllib.request.Request('https://api.github.com'+path,headers={
            'Authorization':'Bearer '+self.key,'Accept':accept,'X-GitHub-Api-Version':'2022-11-28',
            'User-Agent':'katech-sils-private-fetch'})
        return self.opener.open(request,timeout=60)

    def json(self,path):
        try:
            with self.request(path) as response:return json.load(response)
        except urllib.error.HTTPError as exc:raise RuntimeError('GitHub API HTTP '+str(exc.code)) from None

    def private(self):
        repo=self.json('/repos/'+self.repository)
        if repo.get('private') is not True or repo.get('visibility')!='private':
            raise ValueError('C-Track source must remain private')

    def fetch(self,tag,record,destination):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*',tag) or tag.lower()=='latest':raise ValueError('Unpinned release')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*',record['file']):raise ValueError('Unsafe artifact filename')
        if not re.fullmatch('[0-9a-f]{64}',record['sha256']) or type(record['bytes']) is not int or record['bytes']<=0:
            raise ValueError('Unpinned artifact')
        # Check authorization/privacy even when a local cache exists.
        self.private()
        destination=destination.resolve();destination.mkdir(parents=True,exist_ok=True)
        target=destination/record['file']
        if target.exists() or target.is_symlink():
            if target.is_symlink() or target.stat().st_size!=record['bytes'] or digest(target)!=record['sha256']:
                raise ValueError('Existing cache differs; preserved')
            return target
        release=self.json(f'/repos/{self.repository}/releases/tags/{tag}')
        if release.get('draft'):raise ValueError('Draft release refused')
        found=[a for a in release['assets'] if a['name']==record['file']]
        if len(found)!=1:raise ValueError('Release asset missing/ambiguous')
        asset=found[0]
        if asset.get('digest')!='sha256:'+record['sha256'] or asset['size']!=record['bytes'] or asset['state']!='uploaded':
            raise ValueError('Remote release checksum/size mismatch')
        response=None
        try:
            response=self.request(f'/repos/{self.repository}/releases/assets/{int(asset["id"])}','application/octet-stream')
        except urllib.error.HTTPError as exc:
            if exc.code not in (302,303,307,308):raise RuntimeError('Asset download HTTP '+str(exc.code)) from None
            url=exc.headers.get('Location','');parts=urllib.parse.urlsplit(url)
            if parts.scheme!='https' or not parts.hostname or not parts.hostname.endswith('.githubusercontent.com'):
                raise ValueError('Unexpected asset redirect host') from None
            # Fresh request: never attach the API credential to a signed CDN URL.
            response=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'katech-sils-download'}),timeout=60)
        fd,name=tempfile.mkstemp(prefix='.private-download-',dir=destination);temporary=Path(name)
        try:
            count=0;h=hashlib.sha256();reported=time.monotonic()
            with response,os.fdopen(fd,'wb') as output:
                while block:=response.read(1024*1024):
                    count+=len(block)
                    if count>record['bytes']:raise ValueError('Oversized artifact')
                    output.write(block);h.update(block)
                    if time.monotonic()-reported>20:
                        print(json.dumps({'file':record['file'],'percent':round(count/record['bytes']*100,1)}),flush=True)
                        reported=time.monotonic()
            if count!=record['bytes'] or h.hexdigest()!=record['sha256']:raise ValueError('Downloaded checksum mismatch')
            os.link(temporary,target)
        finally:temporary.unlink(missing_ok=True)
        return target

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--map',choices=['ctrack'],required=True)
    args=parser.parse_args()
    catalog=json.loads((ROOT/'map_selection/maps.json').read_text())
    record=next(m for m in catalog['maps'] if m['id']==args.map)
    profile=record['autoware']['runtime_profile_reference'];api=PrivateRelease(profile['repository'])
    base_tag='v1.0.7-assets.20261030'
    for tag,artifact in [(base_tag,record['artifact']),(profile['release_tag'],profile['artifact'])]:
        try:print(api.fetch(tag,artifact,args.cache),flush=True)
        except urllib.error.URLError:raise RuntimeError('Private asset network failure; credential/URLs not logged') from None

if __name__=='__main__':main()
