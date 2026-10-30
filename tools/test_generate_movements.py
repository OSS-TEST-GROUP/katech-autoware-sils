import unittest
import numpy as np
from generate_movements import bindings_for,check_topology_warnings
import xml.etree.ElementTree as ET


class MovementTests(unittest.TestCase):
    def test_unexpected_parser_notice_fails(self):
        with self.assertRaises(ValueError):check_topology_warnings(ET.fromstring('<osm/>'),['missing light'])
    def test_only_declared_speed_bump_notice(self):
        xml=ET.fromstring('<osm><relation id="1"><tag k="type" v="regulatory_element"/><tag k="subtype" v="speed_bump"/></relation></osm>')
        warning='\t- Error parsing primitive 1: Creating a regulatory element of type speed_bump failed: No regulatory element found that implements rule speed_bump'
        self.assertEqual(check_topology_warnings(xml,[warning]),set())
        with self.assertRaises(ValueError):check_topology_warnings(xml,[warning.replace('primitive 1:','primitive 2:')])
    def inputs(self):
        plan={'junctions':[{'id':'test','center_ros':[0,0,0],'extent':[2,2],
              'approaches':[{'key':'incoming','heading':[1,0],'signal_ids':['9']}]}]}
        placements=[{'regulatory_id':'9','lanelet_ids':[1]}]
        def line(start,end):return np.column_stack([np.linspace(start[0],end[0],40),np.linspace(start[1],end[1],40),np.zeros(40)])
        lanes={'1':line([-4,0],[0,0]),'2':line([0,0],[0,4]),'3':line([0,0],[4,0]),'4':line([0,0],[0,-4])}
        return plan,placements,lanes,{'1':['2','3','4']}
    def test_three_directions_and_no_shared_marker(self):
        bindings=bindings_for(*self.inputs())
        self.assertEqual(len(bindings),1)
        self.assertEqual(bindings[0]['markers'],{'2':'left','3':'straight','4':'right'})
        self.assertNotIn('1',bindings[0]['markers'])
    def test_disconnected_exit_fails(self):
        args=list(self.inputs());args[3]={}
        with self.assertRaises(ValueError):bindings_for(*args)
    def test_cycle_fails(self):
        args=list(self.inputs());args[3]={'1':['1']}
        with self.assertRaises(ValueError):bindings_for(*args)
    def test_missing_signal_fails(self):
        args=list(self.inputs());args[1].append({'regulatory_id':'10','lanelet_ids':[1]})
        with self.assertRaises(ValueError):bindings_for(*args)
    def test_signal_paths_do_not_leak_across_heads(self):
        plan,placements,lanes,following=self.inputs()
        plan['junctions'][0]['approaches'][0]['signal_ids'].append('10')
        placements[0]['lanelet_ids']=[1];placements.append({'regulatory_id':'10','lanelet_ids':[5]})
        lanes['5']=lanes['1'].copy();following={'1':['2'],'5':['3']}
        result=bindings_for(plan,placements,lanes,following)
        self.assertEqual(result[0]['markers'],{'2':'left'})
        self.assertEqual(result[1]['markers'],{'3':'straight'})


if __name__=='__main__':unittest.main()
