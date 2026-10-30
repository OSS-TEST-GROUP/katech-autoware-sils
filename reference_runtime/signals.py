"""External visual signal controller. Does NOT impersonate native CARLA traffic lights."""
import math,os
import carla

STATES=['red','yellow','green','redleft','greenleft','off']
ASSET=os.environ.get('KR_SIGNAL_ASSET','/Game/KoreanSignalAddonV4')
SUPPORT_ASSET='/Game/KoreanRoadsideSupportsV2'

class SignalScene:
    def __init__(self,world,placements):
        self.world=world;self.placements=placements;self.heads={};self.supports=[];self.states={}

    def mesh(self,name,pose,role,scale=1.,asset=None):
        bp=self.world.get_blueprint_library().find('static.prop.mesh')
        bp.set_attribute('mesh_path',f'{asset or ASSET}/{name}.{name}');bp.set_attribute('mass','0');bp.set_attribute('scale',str(scale));bp.set_attribute('role_name',role)
        actor=self.world.spawn_actor(bp,pose)
        if max(actor.bounding_box.extent.x,actor.bounding_box.extent.y,actor.bounding_box.extent.z)<.1:
            actor.destroy()
            # A first-time asynchronous static-mesh load can return empty bounds.
            if self.world.get_settings().synchronous_mode:self.world.tick()
            else:self.world.wait_for_tick(10)
            actor=self.world.spawn_actor(bp,pose)
            if max(actor.bounding_box.extent.x,actor.bounding_box.extent.y,actor.bounding_box.extent.z)<.1:
                bounds=str(actor.bounding_box);actor.destroy();raise RuntimeError('Failed to load '+name+' '+bounds)
        return actor

    def pose(self,p):
        return carla.Transform(carla.Location(*p['head_carla']),carla.Rotation(yaw=p['yaw_deg']))

    def set_state(self,p,state):
        assert state in STATES
        ident=p['regulatory_id']
        # Caller uses synchronous mode: replacement is completed before the next tick.
        old=self.heads.pop(ident,None)
        if old:old.destroy()
        self.heads[ident]=self.mesh('SM_KR_'+state,self.pose(p),'kr_signal_'+ident)
        self.states[ident]=state
        return self.heads[ident]

    def deploy(self):
        for p in self.placements:
            self.set_state(p,'red')
            self.supports.append(self.mesh('SM_Support_'+p['regulatory_id'],self.pose(p),'kr_support_'+p['regulatory_id'],asset=SUPPORT_ASSET))

    def all_red(self):
        for p in self.placements:
            if self.states.get(p['regulatory_id'])!='red':self.set_state(p,'red')

    def destroy(self):
        for a in list(self.heads.values())+self.supports:
            if a.is_alive:a.destroy()
        self.heads.clear();self.supports.clear()

def phase_at(t,placements):
    """Conservative demo: only ONE approach is released across the entire scene."""
    index=int(t//18)%len(placements);within=t%18
    if within<2:state='red'
    elif within<10:state='green'
    elif within<14:state='greenleft'
    elif within<16:state='yellow'
    else:state='red'
    return placements[index]['regulatory_id'],state
