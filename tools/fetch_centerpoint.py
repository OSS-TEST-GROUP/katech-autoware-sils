"""Fetch fixed upstream CenterPoint files; no engines, overwrite or credentials."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.parse
import urllib.request
from prepare import ROOT, digest


def validate(row):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*',row['file']):
        raise ValueError('Unsafe filename')
    if not re.fullmatch('[0-9a-f]{64}',row['sha256']):
        raise ValueError('Missing checksum')
    url=urllib.parse.urlsplit(row['url'])
    if url.scheme!='https' or url.netloc!='awf.ml.dev.web.auto' or url.query or url.fragment:
        raise ValueError('Unexpected model origin')
    if url.path!='/perception/models/centerpoint/v2/'+row['file']:
        raise ValueError('Unexpected model path')


def fetch(row,destination,limit):
    validate(row)
    destination.mkdir(parents=True,exist_ok=True)
    target=destination/row['file']
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file() or target.stat().st_size>limit or digest(target)!=row['sha256']:
            raise ValueError('Existing file differs; preserved')
        return target
    fd,name=tempfile.mkstemp(prefix='.centerpoint-',dir=destination)
    temporary=Path(name)
    try:
        request=urllib.request.Request(row['url'],headers={'User-Agent':'katech-autoware-sils/0.1'})
        with os.fdopen(fd,'wb') as output, urllib.request.urlopen(request,timeout=60) as response:
            if urllib.parse.urlsplit(response.geturl()).scheme!='https':
                raise ValueError('Insecure redirect')
            size=0
            while data:=response.read(1024*1024):
                size+=len(data)
                if size>limit:raise ValueError('File size limit exceeded')
                output.write(data)
        if digest(temporary)!=row['sha256']:raise ValueError('Model checksum mismatch')
        os.link(temporary,target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    manifest=json.loads((ROOT/'models/centerpoint.json').read_text())
    results=[]
    for row in manifest['files']:
        path=fetch(row,args.destination.resolve(),manifest['maximum_file_bytes'])
        results.append(dict(file=path.name,bytes=path.stat().st_size,sha256=digest(path)))
        print(json.dumps(results[-1]),flush=True)
    with (args.destination/'download-verification.json').open('w') as output:
        json.dump(dict(files=results,source_commit=manifest['source_commit'],engines_included=False),output,indent=2)


if __name__=='__main__':main()
