"""Explicit installation-local simulator configuration; no implicit live target."""
import ipaddress
import json
import os
from pathlib import Path


def validate(config):
    if config.get('schema')!=1 or config.get('simulation_only') is not True:
        raise ValueError('Simulation-only configuration required')
    if config.get('auto_engage') is not False or config.get('auto_resume') is not False:
        raise ValueError('Automatic engagement/resume is prohibited')
    host=ipaddress.ip_address(config['carla_host'])
    if host.version!=4 or not (host.is_loopback or host in ipaddress.ip_network('172.16.0.0/12')):
        raise ValueError('Use a verified local Docker gateway or loopback')
    if type(config['carla_port']) is not int or not 1024<=config['carla_port']<=65533:
        raise ValueError('Invalid CARLA port')
    if type(config['ros_domain_id']) is not int or not 1<=config['ros_domain_id']<=232:
        raise ValueError('Explicit non-default ROS domain required')
    if type(config.get('headless')) is not bool:raise ValueError('Explicit headless setting required')
    if config.get('render_quality','Epic')!='Epic':
        raise ValueError('C-Track camera inference requires Epic rendering; Low loses lamp appearance')
    if config.get('carla_map')!='/Game/map_package/Maps/C_track_1_0_7/C_track_1_0_7':
        raise ValueError('Only the verified C-Track profile is currently supported')
    return config


def load(path=Path('/results/config/runtime.json')):
    config=validate(json.loads(path.read_text()))
    if os.environ.get('ROS_DOMAIN_ID')!=str(config['ros_domain_id']):
        raise ValueError('ROS domain differs from isolated session')
    return config
