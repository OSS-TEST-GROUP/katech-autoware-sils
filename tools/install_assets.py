"""Install verified archives into a NEW directory; never launch or auto-engage."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile

from prepare import ROOT, digest, load


def relative(name):
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or not p.parts:
        raise ValueError('Unsafe archive path')
    return p


def checked(path, record):
    if path.is_symlink() or not path.is_file() or path.stat().st_size!=record['bytes'] or digest(path)!=record['sha256']:
        raise ValueError('Archive checksum/size mismatch: '+path.name)


def extract(archive, destination, *, private=False, limit=60*1024**3):
    """Reject traversal, special files, collisions and private symlinks.

    tarfile.data_filter is mandatory (available in security-updated Python 3.10).
    No fallback to unsafe extractall is allowed.
    """
    if not hasattr(tarfile,'data_filter'):
        raise RuntimeError('Update Python: tarfile.data_filter is required')
    destination.mkdir(parents=True,exist_ok=False)
    proc=None;size=0;count=0;seen=set()
    try:
        if archive.name.endswith('.zst'):
            proc=subprocess.Popen(['zstd','-dc','--',str(archive)],stdout=subprocess.PIPE)
            stream=tarfile.open(fileobj=proc.stdout,mode='r|')
        else:stream=tarfile.open(archive,mode='r|*')
        with stream:
            for item in stream:
                # Root directory entries are common in official archives.
                if item.name in ('.','./') and item.isdir():continue
                path=relative(item.name)
                if not (item.isfile() or item.isdir() or item.issym() or item.islnk()):
                    raise ValueError('Special archive member refused')
                if private and not (item.isfile() or item.isdir()):
                    raise ValueError('Private archive links refused')
                if str(path) in seen and not item.isdir():raise ValueError('Duplicate archive member')
                seen.add(str(path));size+=item.size
                if size>limit:raise ValueError('Archive expanded size limit exceeded')
                target=destination/path
                if (target.exists() or target.is_symlink()) and not (item.isdir() and target.is_dir() and not target.is_symlink()):
                    raise ValueError('Archive collision refused')
                stream.extract(item,destination,filter='data')
                if item.isfile():count+=1
        if proc and proc.wait()!=0:raise RuntimeError('zstd decompression failed')
    finally:
        if proc:
            proc.stdout.close()
            if proc.poll() is None:proc.terminate();proc.wait()
    return {'files':count,'expanded_bytes':size}


def verify_manifest(directory, filename):
    records=json.loads((directory/filename).read_text())['files'];seen=set()
    for row in records:
        p=relative(row['path'])
        if str(p) in seen:raise ValueError('Duplicate manifest entry')
        seen.add(str(p));checked(directory/p,row)
    actual={str(p.relative_to(directory)) for p in directory.rglob('*') if p.is_file()}
    if actual!=seen|{filename}:raise ValueError('Unlisted or missing private payload')
    return len(records)


def install(downloads,destination,map_id):
    if destination.exists() or destination.is_symlink():raise ValueError('Use a new installation directory; existing files preserved')
    catalog=load('map_selection/maps.json')
    selected=next((m for m in catalog['maps'] if m['id']==map_id),None)
    if selected is None:raise ValueError('Unknown map')
    carla=load('carla.lock.json');carla_file=downloads/'carla/CARLA_0.9.15.tar.gz';checked(carla_file,carla)
    if selected['distribution']=='private_github_release':
        base=selected['artifact'];profile=selected['autoware']['runtime_profile_reference']['artifact']
        checked(downloads/'private'/base['file'],base);checked(downloads/'private'/profile['file'],profile)
    destination.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(destination.parent).free<60*1024**3:raise ValueError('At least 60 GiB of free installation space required')
    destination.mkdir(mode=0o700)
    report={'schema':1,'map_id':map_id,'carla_map':selected['carla_map'],'carla_sha256':carla['sha256'],
            'runtime_ready':False,'auto_engage':False,'steps':{}}
    # Any failed partial installation remains in this NEW folder for diagnosis.
    report['steps']['carla']=extract(carla_file,destination/'carla')
    binary=destination/'carla/CarlaUE4/Binaries/Linux/CarlaUE4-Linux-Shipping'
    if not binary.is_file() or not os.access(binary,os.X_OK):raise ValueError('CARLA executable missing')
    if selected['distribution']=='private_github_release':
        private_root=destination/'private'
        report['steps']['base']=extract(downloads/'private'/base['file'],private_root,private=True,limit=6*1024**3)
        report['steps']['base_verified_files']=verify_manifest(private_root,'private-assets-manifest.json')
        report['steps']['profile']=extract(downloads/'private'/profile['file'],destination/'profile',private=True,limit=512*1024**2)
        report['steps']['profile_verified_files']=verify_manifest(destination/'profile','runtime-profile-manifest.json')
        allowed={'map_package','KoreanSignalAddonV4','KoreanRoadsideSupportsV2'}
        content=private_root/'CarlaUE4/Content'
        if {p.name for p in content.iterdir()}!=allowed:raise ValueError('Unexpected private CARLA namespaces')
        for name in sorted(allowed):
            target=destination/'carla/CarlaUE4/Content'/name
            if target.exists() or target.is_symlink():raise ValueError('Official CARLA namespace collision: '+name)
            # Move only this new installation's own verified payload, no duplication.
            (content/name).rename(target)
        config=destination/'profile/sils_map_config'
        contract=json.loads((config/'profile.json').read_text())
        lane=private_root/relative(contract['lanelet']['path'])
        pcd=destination/'profile'/relative(contract['pointcloud']['path'])
        if digest(lane)!=contract['lanelet']['sha256'] or digest(pcd)!=contract['pointcloud']['sha256']:
            raise ValueError('Selected map does not match private profile')
        if pcd!=config/'ndt/pointcloud_map.pcd':raise ValueError('Wrong NDT PCD selected')
        selected_map=destination/'autoware_map';selected_map.mkdir()
        for source,name in [(lane,'lanelet2_map.osm'),(pcd,'pointcloud_map.pcd'),(config/'map_projector_info.yaml','map_projector_info.yaml')]:
            shutil.copy2(source,selected_map/name)
        report.update(base_asset_sha256=base['sha256'],profile_sha256=profile['sha256'],
                      selected_map={'lanelet_sha256':digest(lane),'pcd_sha256':digest(pcd),
                                    'pcd_source':'profile/sils_map_config/ndt/pointcloud_map.pcd',
                                    'legacy_pcd_used':False})
    (destination/'assets-installation.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--downloads',type=Path,required=True)
    p.add_argument('--destination',type=Path,required=True)
    p.add_argument('--map',choices=['ctrack','town01','town10hd'],required=True)
    a=p.parse_args();print(json.dumps(install(a.downloads.resolve(),a.destination.absolute(),a.map),indent=2))


if __name__=='__main__':main()
