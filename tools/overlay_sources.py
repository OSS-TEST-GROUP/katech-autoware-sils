"""Apply reviewed SILS native sources ONLY to a fresh prepared source tree.

Generated movement headers are private. Never push this resulting Autoware tree
or its decision image to a public repository/registry.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from prepare import ROOT,digest,load,run


def state(destination):
    import yaml
    paths=['.']+['src/'+n for n in yaml.safe_load((ROOT/'autoware.repos').read_text())['repositories']]
    results={}
    for name in paths:
        path=destination/name
        diff=subprocess.check_output(['git','-C',str(path),'diff','--binary','HEAD'])
        files=subprocess.check_output(['git','-C',str(path),'ls-files','--others','--exclude-standard'],text=True).splitlines()
        # Top-level build outputs are not source changes; tracked changes remain checked.
        if name=='.':files=[]
        results[name]={'head':subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip(),
                       'diff_sha256':hashlib.sha256(diff).hexdigest(),'untracked':{n:digest(path/n) for n in files}}
    safety=destination/'src/sils'
    results['generated_safety_package']={str(p.relative_to(safety)):digest(p) for p in sorted(safety.rglob('*')) if p.is_file()}
    return results


def apply(destination,installation):
    destination=destination.resolve();installation=installation.resolve()
    if destination==ROOT or ROOT in destination.parents:raise ValueError('Private generated sources must be outside public repository')
    if (destination/'.sils-overlay.json').exists():raise ValueError('Overlay already exists; use verification, not reapplication')
    # Reuse the strict baseline preflight without starting Docker.
    import prepare
    original=prepare.run
    def checked_run(args,**kw):
        if args[:2]==['bash','partition/partition_build.sh']:return
        return original(args,**kw)
    prepare.run=checked_run
    try:prepare.build_base(destination)
    finally:prepare.run=original
    generated=installation/'generated/movements'
    binding=json.loads((generated/'movement_bindings.json').read_text())
    if digest(installation/'autoware_map/lanelet2_map.osm')!=binding['map_sha256']:raise ValueError('Map changed after generation')
    for name,key in [('movement_bindings.hpp','header_sha256'),('movement_test_cases.hpp','cases_sha256')]:
        if digest(generated/name)!=binding[key]:raise ValueError('Generated header changed')
    universe=destination/'src/universe/autoware.universe'
    patch=ROOT/'patches/planner-lifetime.patch'
    run(['git','apply','--check',str(patch)],cwd=universe)
    package=universe/'planning/behavior_velocity_planner/autoware_behavior_velocity_traffic_light_module'
    sources=ROOT/'reference_runtime/planning'
    if not (package/'src/scene.cpp').is_file():raise ValueError('Unsupported native package layout')
    launch=universe/'obigo_launch/launch/components/tier4_perception_component.launch.xml'
    text=launch.read_text();needle='<arg name="use_traffic_light_recognition" default="true"'
    if text.count(needle)!=1:raise ValueError('Unexpected native recognition configuration')
    run(['git','apply',str(patch)],cwd=universe)
    for file in (sources/'traffic_light_module').iterdir():
        if not file.is_file():continue
        target=package/('src' if file.suffix in {'.hpp','.cpp'} else '')/file.name
        shutil.copy2(file,target)
    for name in ('protected_turn_policy.hpp','protected_turn_policy_test.cpp'):
        shutil.copy2(sources/name,package/'src'/name)
    for name in ('movement_bindings.hpp','movement_test_cases.hpp'):shutil.copy2(generated/name,package/'src'/name)
    bridge=universe/'simulator/autoware_carla_interface/src/autoware_carla_interface'
    for name in ('carla_ros.py','carla_autoware.py'):
        if not (bridge/name).is_file():raise ValueError('Unsupported bridge layout')
        shutil.copy2(ROOT/'reference_runtime/overlay'/name,bridge/name)
    # Guarded trained recognition is launched separately. Do not run two publishers.
    launch.write_text(text.replace(needle,'<arg name="use_traffic_light_recognition" default="false"'))
    safety=destination/'src/sils/katech_sils_safety';safety.mkdir(parents=True,exist_ok=False)
    for name in ('stop_distance_guard.cpp','plugin_lifetime.c'):shutil.copy2(sources/name,safety/name)
    (safety/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.14)
project(katech_sils_safety LANGUAGES C CXX)
find_package(ament_cmake REQUIRED)
add_library(stop_distance_guard SHARED stop_distance_guard.cpp)
target_compile_features(stop_distance_guard PRIVATE cxx_std_17)
target_link_libraries(stop_distance_guard dl)
add_library(plugin_lifetime SHARED plugin_lifetime.c)
target_link_libraries(plugin_lifetime dl)
install(TARGETS stop_distance_guard plugin_lifetime LIBRARY DESTINATION lib)
ament_package()
''')
    (safety/'package.xml').write_text('''<?xml version="1.0"?>
<package format="3"><name>katech_sils_safety</name><version>0.1.0</version>
<description>Simulator planning domain and plugin lifetime guards</description>
<maintainer email="noreply@github.com">OSS-TEST-GROUP</maintainer>
<license>Apache-2.0</license><buildtool_depend>ament_cmake</buildtool_depend>
<export><build_type>ament_cmake</build_type></export></package>
''')
    # The standalone safety package is compiled into the decision image only.
    config=destination/'partition/partition_config/sample-adsw-decision.json'
    row=json.loads(config.read_text());row['packages'].append('katech_sils_safety');row['folders'].append('src/sils')
    config.write_text(json.dumps(row,indent=2)+'\n')
    record={'schema':1,'map_sha256':binding['map_sha256'],'private_generated_code':True,
            'do_not_push_public':True,'source_state':state(destination),'full_sils_integration_complete':False}
    (destination/'.sils-overlay.json').write_text(json.dumps(record,indent=2)+'\n')
    return {'native_overlay_prepared':True,'private_map_bindings':True,'built':False}


def verify(destination):
    record=json.loads((destination/'.sils-overlay.json').read_text())
    if not record.get('private_generated_code') or state(destination)!=record['source_state']:
        raise ValueError('SILS sources changed since overlay preparation')
    return record


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['apply','verify'])
    p.add_argument('--destination',type=Path,required=True);p.add_argument('--installation',type=Path)
    a=p.parse_args()
    if a.action=='apply':
        if not a.installation:p.error('--installation required')
        print(json.dumps(apply(a.destination,a.installation),indent=2))
    else:verify(a.destination);print('Overlay source state verified; this is not a runtime qualification')
