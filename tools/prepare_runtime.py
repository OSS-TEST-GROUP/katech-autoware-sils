"""Create a new private runtime profile from verified assets; never start/engage."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import uuid
import yaml
from prepare import ROOT, digest
from install_assets import verify_manifest, relative
from ndt_profile import bounded_step_profile

sys.path.insert(0,str(ROOT/'reference_runtime'))
from runtime_config import validate


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as output:json.dump(value,output,indent=2);output.write('\n')


def prepare(installation,share,destination,host,port,domain,headless=True):
    if destination.exists() or destination.is_symlink():raise ValueError('New runtime folder required')
    if destination==ROOT or ROOT in destination.parents:raise ValueError('Private runtime must be outside public repository')
    installed=json.loads((installation/'assets-installation.json').read_text())
    if installed['map_id']!='ctrack':raise ValueError('Only C-Track runtime is implemented')
    config=installation/'profile/sils_map_config'
    verify_manifest(installation/'profile','runtime-profile-manifest.json')
    profile=json.loads((config/'profile.json').read_text())
    for key,name in [('lanelet','lanelet2_map.osm'),('pointcloud','pointcloud_map.pcd')]:
        if digest(installation/'autoware_map'/name)!=profile[key]['sha256']:raise ValueError('Map/PCD mismatch')
    runtime=validate(dict(schema=1,simulation_only=True,auto_engage=False,auto_resume=False,
                          carla_host=host,carla_port=port,ros_domain_id=domain,headless=headless,render_quality='Epic',
                          carla_map=installed['carla_map'],installation_id=str(uuid.uuid4())))
    if not (share/'launch/adsw_perception.launch.xml').is_file():raise ValueError('Extract the new native obigo_launch share first')
    destination.mkdir(parents=True,mode=0o700)
    for folder in ('logs','reports','tmp','cache','server_user','ndt_integration_v1','config','signal_network_v1'):
        (destination/folder).mkdir()
    for name in ('start.json','signal_map.json','objects.json','vehicle_info.param.yaml','sensor_kit_calibration.yaml'):
        shutil.copy2(config/name,destination/'config'/name)
    for name in ('plan.json','placements.json'):
        shutil.copy2(config/name,destination/'signal_network_v1'/name)
    shutil.copytree(share,destination/'share/obigo_launch')
    if not headless:
        from gui_support import configure_rviz
        rviz=destination/'share/obigo_launch/rviz/autoware.rviz'
        rviz.write_text(yaml.safe_dump(configure_rviz(yaml.safe_load(rviz.read_text())),sort_keys=False))
    launch_config=destination/'share/obigo_launch/config'
    localization=json.loads((config/'localization.json').read_text())
    if localization['pose_source']!='ndt' or localization['ground_truth_pose_relay'] is not False:
        raise ValueError('Expected NDT profile without GT relay')
    for target,source in localization['config_overrides'].items():
        original=installation/'profile'/relative(source)
        output=launch_config/relative(target)
        if not output.is_file():raise ValueError('Missing native NDT config override target: '+target)
        shutil.copy2(original,output)
    ndt_path=launch_config/'localization/ndt_scan_matcher/ndt_scan_matcher.param.yaml'
    ndt_configuration=bounded_step_profile(yaml.safe_load(ndt_path.read_text()))
    ndt_path.write_text(yaml.safe_dump(ndt_configuration,sort_keys=False))
    speed=launch_config/'planning/scenario_planning/common/common.param.yaml'
    params=yaml.safe_load(speed.read_text())
    params['/**']['ros__parameters']['max_vel']=50./3.6
    speed.write_text(yaml.safe_dump(params))
    longitudinal=launch_config/'control/trajectory_follower/longitudinal/pid.param.yaml'
    if not longitudinal.is_file():raise ValueError('Missing native control config')
    shutil.copy2(config/'control/longitudinal_slope.param.yaml',longitudinal)
    shutil.copytree(ROOT/'reference_runtime',destination/'code',ignore=shutil.ignore_patterns('__pycache__'))
    save(destination/'config/runtime.json',runtime)
    save(destination/'config/ndt_active.json',localization)
    save(destination/'config/signal_network_active.json',dict(enabled=True,simulation_only=True))
    save(destination/'code/runtime_storage27.json',dict(runtime='/results',installation_id=runtime['installation_id'],
         supervisor='host-owned clean-install supervisor; checks RAID identity/error count, free space, log budget and process ownership'))
    result=dict(schema=1,installation_id=runtime['installation_id'],map_sha256=profile['lanelet']['sha256'],
                pcd_sha256=profile['pointcloud']['sha256'],config_source='verified private profile and freshly built native share',
                ndt_optimizer_override=dict(step_size=.05,trans_epsilon=.01,safety_score_thresholds_changed=False),
                starts_simulation=False,auto_engage=False,full_integration_complete=False)
    save(destination/'prepared-runtime.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--installation',type=Path,required=True)
    p.add_argument('--native-share',type=Path,required=True)
    p.add_argument('--destination',type=Path,required=True)
    p.add_argument('--host',default='127.0.0.1')
    p.add_argument('--port',type=int,default=2480)
    p.add_argument('--domain',type=int,default=222)
    a=p.parse_args()
    print(json.dumps(prepare(a.installation.resolve(),a.native_share.resolve(),a.destination.resolve(),a.host,a.port,a.domain),indent=2))
