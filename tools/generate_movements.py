"""Generate private movement bindings from the exact installed Lanelet/plan.

Requires native Lanelet2 Python bindings and NumPy. Outputs contain private map
identifiers and MUST stay outside the public source repository.
"""
import argparse
import collections
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from prepare import ROOT,digest


def interpolate(points,n=40):
    a=np.asarray(points,float);s=np.r_[0,np.cumsum(np.linalg.norm(np.diff(a[:,:2],axis=0),axis=1))]
    if s[-1]<1e-8:return np.repeat(a[:1],n,axis=0)
    return np.stack([np.interp(np.linspace(0,s[-1],n),s,a[:,i]) for i in range(3)],axis=1)


def geometry(path):
    xml=ET.parse(path).getroot();nodes={}
    for n in xml.findall('node'):
        t={a.get('k'):a.get('v') for a in n.findall('tag')}
        nodes[n.get('id')]=[float(t['local_x']),float(t['local_y']),float(t['ele'])]
    ways={w.get('id'):[nodes[n.get('ref')] for n in w.findall('nd')] for w in xml.findall('way')};lanes={}
    for r in xml.findall('relation'):
        tags={t.get('k'):t.get('v') for t in r.findall('tag')}
        if tags.get('type')!='lanelet' or tags.get('subtype')!='road':continue
        members={m.get('role'):m.get('ref') for m in r.findall('member')}
        left=interpolate(ways[members['left']]);right=interpolate(ways[members['right']])
        if np.linalg.norm(left[0]-right[0])+np.linalg.norm(left[-1]-right[-1])>np.linalg.norm(left[0]-right[-1])+np.linalg.norm(left[-1]-right[0]):right=right[::-1]
        center=(left+right)/2;v=center[-1,:2]-center[0,:2];side=np.mean(right-left,axis=0)[:2]
        if v[0]*side[1]-v[1]*side[0]>0:center=center[::-1]
        lanes[r.get('id')]=center
    return xml,lanes


def check_topology_warnings(xml,errors):
    """Stock Lanelet2 lacks Autoware speed_bump; allow only those exact notices.

    This tool reads FOLLOWING connectivity, not speed/stop rules. The original
    map remains unchanged and Autoware's loader still receives all speed bumps.
    Any other parser issue is fatal, including missing lights or lane geometry.
    """
    bumps=set();lanelets=set();allowed={'Errors ocurred while parsing Lanelet Map:'}
    relations=xml.findall('relation')
    for r in relations:
        tags={t.get('k'):t.get('v') for t in r.findall('tag')}
        if tags.get('type')=='regulatory_element' and tags.get('subtype')=='speed_bump':bumps.add(r.get('id'))
        if tags.get('type')=='lanelet':lanelets.add(int(r.get('id')))
    for ident in bumps:
        allowed.add(f'\t- Error parsing primitive {ident}: Creating a regulatory element of type speed_bump failed: No regulatory element found that implements rule speed_bump')
    for r in relations:
        for m in r.findall('member'):
            if m.get('role')=='regulatory_element' and m.get('ref') in bumps:
                allowed.add(f'\t- Error parsing primitive {r.get("id")}: Failed to get id {m.get("ref")} from map')
    if any(str(e) not in allowed for e in errors):raise ValueError('Unexpected native Lanelet2 parser error; review required')
    return lanelets


def bindings_for(plan,placements,lanes,following):
    byreg={int(p['regulatory_id']):p for p in placements};bindings=[]
    for j in plan['junctions']:
        center=np.array(j['center_ros'][:2]);extent=np.array(j['extent'])
        for a in j['approaches']:
            for reg in a['signal_ids']:
                paths=[]
                def visit(ident,prev,entered,length):
                    if ident in prev or len(prev)>=16 or length>=180:raise ValueError('Unresolved cyclic/long intersection path')
                    c=lanes[ident][:,:2];inside=np.all(abs(c-center)<=extent,axis=1)
                    entered=entered or bool(inside.any());ids=prev+[ident]
                    length+=float(np.linalg.norm(np.diff(c,axis=0),axis=1).sum())
                    if entered and not inside[-1]:
                        v=c[-1]-c[-5];norm=np.linalg.norm(v)
                        if norm<1e-6:raise ValueError('Degenerate exit heading')
                        v=v/norm;h=np.array(a['heading'])
                        angle=math.degrees(math.atan2(h[0]*v[1]-h[1]*v[0],np.dot(h,v)))
                        turn='left' if 35<angle<145 else 'right' if -145<angle<-35 else 'straight' if abs(angle)<=35 else 'unknown'
                        if turn=='unknown':raise ValueError('Ambiguous/U-turn path; manual map review required')
                        paths.append(dict(lane_ids=ids,turn=turn,exit_angle_deg=angle));return
                    nxt=[i for i in following.get(ident,[]) if i in lanes]
                    if not nxt:raise ValueError('Intersection exit missing')
                    for i in nxt:visit(i,ids,entered,length)
                incoming=byreg[int(reg)]['lanelet_ids']
                for ident in incoming:visit(str(ident),[],False,0.)
                if not paths:raise ValueError('No signal movement paths')
                directions=collections.defaultdict(set)
                for p in paths:
                    for ident in p['lane_ids']:directions[ident].add(p['turn'])
                markers={ident:next(iter(ds)) for ident,ds in directions.items() if len(ds)==1}
                for ident in incoming:markers.pop(str(ident),None)
                if any(not any(i in markers for i in p['lane_ids']) for p in paths):raise ValueError('Route cannot resolve a unique movement')
                bindings.append(dict(regulatory_id=int(reg),junction=j['id'],approach=a['key'],incoming_lane_ids=incoming,paths=paths,markers=markers))
    if len(bindings)!=len(byreg):raise ValueError('Some signal heads have no generated movement binding')
    return bindings


def generate(installation):
    import lanelet2
    installation=installation.resolve()
    if installation==ROOT or ROOT in installation.parents:raise ValueError('Private outputs must be outside public repository')
    destination=installation/'generated/movements'
    if destination.exists():raise ValueError('Existing generated bindings preserved')
    report=json.loads((installation/'assets-installation.json').read_text())
    if report['map_id']!='ctrack':raise ValueError('No configured movement profile for this map')
    path=installation/'autoware_map/lanelet2_map.osm'
    if digest(path)!=report['selected_map']['lanelet_sha256']:raise ValueError('Installed lanelet changed')
    config=installation/'profile/sils_map_config'
    xml,lanes=geometry(path);node=xml.find('node')
    projector=lanelet2.projection.UtmProjector(lanelet2.io.Origin(float(node.get('lat')),float(node.get('lon'))))
    native,errors=lanelet2.io.loadRobust(str(path),projector)
    expected_lanelets=check_topology_warnings(xml,errors)
    if {l.id for l in native.laneletLayer}!=expected_lanelets:raise ValueError('Native parser omitted lanelets')
    rules=lanelet2.traffic_rules.create(lanelet2.traffic_rules.Locations.Germany,lanelet2.traffic_rules.Participants.Vehicle)
    graph=lanelet2.routing.RoutingGraph(native,rules)
    following={str(l.id):[str(n.id) for n in graph.following(l)] for l in native.laneletLayer}
    plan=json.loads((config/'plan.json').read_text());placements=json.loads((config/'placements.json').read_text())
    if not {int(p['regulatory_id']) for p in placements}.issubset({r.id for r in native.regulatoryElementLayer}):
        raise ValueError('Native parser omitted traffic-light rules')
    bindings=bindings_for(plan,placements,lanes,following)
    header=['// Private, generated from the installed map; never publish this output.','#pragma once','#include <cstdint>','#include <vector>',
            'namespace ctrack_protected {','enum class Turn { Unknown, Straight, Left, Right };',
            'struct Binding { int64_t signal; int64_t lane; Turn turn; };','inline const std::vector<Binding> bindings = {']
    tests=['#pragma once','struct MovementCase { int64_t signal; std::vector<int64_t> lanes; ctrack_protected::Turn turn; };',
           'inline const std::vector<MovementCase> movement_cases = {']
    for binding in bindings:
        for ident,turn in sorted(binding['markers'].items(),key=lambda x:int(x[0])):
            header.append(f'  {{{binding["regulatory_id"]}, {int(ident)}, Turn::{turn.title()}}},')
        for p in binding['paths']:
            ids=','.join(str(int(i)) for i in p['lane_ids'])
            tests.append('  {'+str(binding['regulatory_id'])+', {'+ids+'}, ctrack_protected::Turn::'+p['turn'].title()+'},')
    header+=['};','}'];tests+=['};']
    destination.mkdir(parents=True,mode=0o700)
    for name,lines in [('movement_bindings.hpp',header),('movement_test_cases.hpp',tests)]:
        (destination/name).write_text('\n'.join(lines)+'\n')
    record={'schema':1,'map_sha256':digest(path),'plan_sha256':digest(config/'plan.json'),
            'placements_sha256':digest(config/'placements.json'),'following':following,'bindings':bindings,
            'topology_only_parser_notices':list(errors),'original_map_modified':False,
            'header_sha256':digest(destination/'movement_bindings.hpp'),'cases_sha256':digest(destination/'movement_test_cases.hpp')}
    (destination/'movement_bindings.json').write_text(json.dumps(record,indent=2)+'\n')
    return {'signals':len(bindings),'movement_cases':sum(len(b['paths']) for b in bindings),
            'topology_only_parser_notices':len(errors),'source':'installed private inputs + native Lanelet2 routing','runtime_activated':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--installation',type=Path,required=True)
    print(json.dumps(generate(p.parse_args().installation),indent=2))
